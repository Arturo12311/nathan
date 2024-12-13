import time
import random
import json
import traceback
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler
from threading import Thread
import os
import sys
import re

#################################
# Configuration
#################################
SCRAPE_INTERVAL = 15  # minutes
LINKS_FILE = 'links.json'
DATA_FILE = 'data.json'
LOG_FILE = 'scraper.log'

# Email Notification Settings
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_ADDRESS = 'sdffd9327@gmail.com'
EMAIL_PASSWORD = 'egaa pozj yuia etml'  
RECIPIENTS = [
    'sdffd9327@gmail.com',
    'nanabitbol@gmail.com'
]

#################################
# Logging Setup
#################################
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

#################################
# Uncaught Exception Handler
#################################
def exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    print("An uncaught exception occurred. Check scraper.log for details.")

sys.excepthook = exception_handler

#################################
# Flask Dashboard
#################################
app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Product Monitoring Dashboard</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            padding: 12px;
            border: 1px solid #ccc;
            text-align: center;
        }
        th {
            background-color: #f4f4f4;
        }
        .in-stock { background-color: #d4edda; }
        .out-of-stock { background-color: #f8d7da; }
        .error { background-color: #fff3cd; }
    </style>
</head>
<body>
    <h1>Product Monitoring Dashboard</h1>
    <table>
        <tr>
            <th>Site</th>
            <th>Product Name</th>
            <th>URL</th>
            <th>Price</th>
            <th>Availability</th>
            <th>Status</th>
        </tr>
        {% for product in products %}
        <tr class="
            {% if product.availability == 'InStock' %}
                in-stock
            {% elif product.availability == 'OutOfStock' %}
                out-of-stock
            {% else %}
                error
            {% endif %}
        ">
            <td>{{ product.site }}</td>
            <td>{{ product.name }}</td>
            <td><a href="{{ product.url }}" target="_blank">Link</a></td>
            <td>
                {% if product.price %}
                    ${{ "{:.2f}".format(product.price) }}
                {% else %}
                    N/A
                {% endif %}
            </td>
            <td>{{ product.availability }}</td>
            <td>
                {% if product.error %}
                    Error ({{ product.error }})
                {% else %}
                    OK
                {% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
"""

@app.route('/')
def dashboard():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
        products = []
        for url, details in data.items():
            products.append({
                'site': details.get('site', 'Unknown'),
                'url': url,
                'name': details.get('name', 'N/A'),
                'price': details.get('price'),
                'availability': details.get('availability', 'Unknown'),
                'error': details.get('error')
            })
        return render_template_string(HTML_TEMPLATE, products=products)
    except Exception as e:
        logging.error(f"Error loading dashboard: {e}")
        return "Failed to load dashboard."

#################################
# Email Notification
#################################
def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = ", ".join(RECIPIENTS)
        msg['Subject'] = subject

        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, RECIPIENTS, text)
        server.quit()
        logging.info(f"Notification email sent to {', '.join(RECIPIENTS)}: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

#################################
# Utility Functions
#################################
def load_links():
    try:
        with open(LINKS_FILE, 'r') as f:
            links = json.load(f)
        logging.info(f"Loaded {len(links)} links.")
        return links
    except Exception as e:
        logging.error(f"Failed to load links: {e}")
        return []

def load_existing_data():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        logging.info("No existing data found. Starting fresh.")
        return {}
    except Exception as e:
        logging.error(f"Failed to load existing data: {e}")
        return {}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save data: {e}")

def random_delay(min_delay=2, max_delay=5):
    time.sleep(random.uniform(min_delay, max_delay))

def get_driver(headless=False):
    options = uc.ChromeOptions()
    # Minimal arguments
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options)
    return driver

def fallback_name_from_url(url):
    # Try to extract something readable from the URL
    # E.g. .../product/4000322419.html -> "4000322419"
    # Or split by '/' and take the last segment
    segment = url.split('/')[-1]
    # Remove query params
    segment = segment.split('?')[0]
    # Replace dashes with spaces and try to capitalize
    name = re.sub(r'[-_]', ' ', segment)
    return name.strip().title() if name.strip() else "Unknown Product"

def wait_for_price(driver, xpath, max_tries=3):
    # Try multiple times if price is '--'
    wait = WebDriverWait(driver, 10)
    for _ in range(max_tries):
        try:
            elem = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            text = elem.text.strip()
            if text and text != "--":
                return text
            time.sleep(3)  # wait and retry if still '--'
        except:
            time.sleep(3)
    return None

#################################
# Extractors
#################################
def extract_name_generic(driver):
    candidates = [
        "//h1", 
        "//h1[@data-automation='product-title']",
        "//span[@id='productTitle']"
    ]
    for xpath in candidates:
        try:
            elem = driver.find_element(By.XPATH, xpath)
            if elem.text.strip():
                return elem.text.strip()
        except:
            continue
    # If no name found from these candidates, fallback to title
    if driver.title and driver.title.strip():
        return driver.title.strip()
    return None

def extract_info_walmart(driver, url):
    try:
        logging.info(f"Navigating to Walmart URL: {url}")
        driver.get(url)
        random_delay()

        page_source = driver.page_source
        if "We like real shoppers, not robots" in page_source:
            logging.warning(f"Walmart bot detection: {url}")
            return {
                'name': fallback_name_from_url(url),
                'price': None,
                'availability': 'Error',
                'error': 'Bot detection'
            }

        # Try name
        name = extract_name_generic(driver)
        if not name:
            name = fallback_name_from_url(url)

        # Check out of stock
        if "Out of stock" in page_source:
            return {
                'name': name,
                'price': None,
                'availability': 'OutOfStock'
            }

        # Try price
        price_xpaths = [
            "//span[@itemprop='price']",
            "//span[contains(@class, 'price')]",
            "//div[@class='price-section']//span[@class='value']"
        ]
        price = None
        for xp in price_xpaths:
            price_text = wait_for_price(driver, xp, max_tries=3)
            if price_text:
                try:
                    price = float(price_text.replace('$', '').replace(',', '').strip())
                    break
                except:
                    continue

        if price is not None:
            return {
                'name': name,
                'price': price,
                'availability': 'InStock'
            }
        else:
            # No price found after tries
            return {
                'name': name,
                'price': None,
                'availability': 'OutOfStock'
            }

    except Exception as e:
        logging.error(f"Error scraping Walmart {url}: {e}")
        return {
            'name': fallback_name_from_url(url),
            'price': None,
            'availability': 'Error',
            'error': str(e)
        }

def extract_info_costco(driver, url):
    try:
        logging.info(f"Navigating to Costco URL: {url}")
        driver.get(url)
        random_delay()

        # Extract name
        try:
            name_elem = driver.find_element(By.XPATH, "//h1[@itemprop='name' and @automation-id='productName']")
            name = name_elem.text.strip() if name_elem.text.strip() else fallback_name_from_url(url)
        except:
            name = extract_name_generic(driver)
            if not name:
                name = fallback_name_from_url(url)

        # Check price
        price_text = wait_for_price(driver, "//span[@automation-id='productPriceOutput']", max_tries=3)
        price = None
        if price_text:
            try:
                price = float(price_text.replace('$', '').replace(',', '').strip())
            except:
                price = None

        # Determine availability
        # If no price at all after tries, assume OutOfStock
        # If price exists, check add-to-cart
        if price is None:
            availability = 'OutOfStock'
        else:
            # Check add-to-cart
            try:
                add_to_cart_btn = driver.find_element(By.XPATH, "//input[@id='add-to-cart-btn' and @automation-id='addToCartButton']")
                if add_to_cart_btn.is_enabled():
                    availability = 'InStock'
                else:
                    availability = 'OutOfStock'
            except:
                # No add-to-cart found but we got a price
                # Assume InStock since price is visible
                availability = 'InStock'

        return {
            'name': name,
            'price': price,
            'availability': availability
        }

    except Exception as e:
        logging.error(f"Error scraping Costco {url}: {e}")
        return {
            'name': fallback_name_from_url(url),
            'price': None,
            'availability': 'Error',
            'error': str(e)
        }

def extract_info_pokemon_center(driver, url):
    # Skip due to captcha
    logging.info(f"Skipping Pokémon Center URL due to captcha: {url}")
    return {
        'name': fallback_name_from_url(url),
        'price': None,
        'availability': 'Pending',
        'error': 'Skipped due to captcha'
    }

#################################
# Main Scraping Logic
#################################
def scrape_all(driver, links, existing_data):
    updated_data = existing_data.copy()
    change_count = 0
    notification_count = 0

    for item in links:
        site = item.get('site')
        url = item.get('url')
        if not site or not url:
            logging.warning(f"Invalid link entry: {item}")
            continue

        try:
            if 'walmart' in site.lower():
                data = extract_info_walmart(driver, url)
            elif 'costco' in site.lower():
                data = extract_info_costco(driver, url)
            elif 'pokemoncenter' in site.lower():
                data = extract_info_pokemon_center(driver, url)
            else:
                data = {
                    'name': fallback_name_from_url(url),
                    'price': None,
                    'availability': 'Error',
                    'error': 'Unsupported website'
                }

            data['site'] = site
            prev_data = updated_data.get(url, {})

            # If error present, store and continue
            if data.get('error'):
                updated_data[url] = data
                save_data(updated_data)
                continue

            # Detect changes
            change_detected = False
            notification_subject = ""
            notification_body = ""

            if prev_data:
                if prev_data.get('price') != data.get('price'):
                    change_detected = True
                    notification_subject += "Price Change Detected\n"
                    notification_body += f"Product: {data.get('name','N/A')}\nURL: {url}\nOld Price: {prev_data.get('price')}\nNew Price: {data.get('price')}\n\n"

                if prev_data.get('availability') != data.get('availability'):
                    change_detected = True
                    notification_subject += "Availability Change Detected\n"
                    notification_body += f"Product: {data.get('name','N/A')}\nURL: {url}\nOld Availability: {prev_data.get('availability')}\nNew Availability: {data.get('availability')}\n\n"
            else:
                # New product
                change_detected = True
                notification_subject += "New Product Added for Monitoring\n"
                notification_body += f"Product: {data.get('name','N/A')}\nURL: {url}\nPrice: {data.get('price')}\nAvailability: {data.get('availability')}\n\n"

            if change_detected and notification_body:
                if "Price Change" in notification_subject and "Availability Change" in notification_subject:
                    subject = "Price and Availability Change Detected"
                elif "Price Change" in notification_subject:
                    subject = "Price Change Detected"
                elif "Availability Change" in notification_subject:
                    subject = "Availability Change Detected"
                elif "New Product Added" in notification_subject:
                    subject = "New Product Added for Monitoring"
                else:
                    subject = "Product Update"

                send_email(subject, notification_body)
                notification_count += 1
                change_count += 1

            updated_data[url] = data
            save_data(updated_data)

        except Exception as e:
            logging.error(f"Error processing {url}: {e}")
            continue

    logging.info(f"Cycle completed: {change_count} changes, {notification_count} notifications.")
    return updated_data

def perform_scraping():
    logging.info("Starting scrape cycle.")
    links = load_links()
    existing_data = load_existing_data()

    headless_mode = False
    driver = get_driver(headless=headless_mode)
    try:
        updated_data = scrape_all(driver, links, existing_data)
        # Data saved incrementally in scrape_all
    except Exception as e:
        logging.error(f"Unexpected error during scraping: {e}")
        logging.error(traceback.format_exc())
    finally:
        driver.quit()
        logging.info("Scrape cycle finished.")

def start_flask():
    logging.info("Dashboard server started.")
    app.run(host='0.0.0.0', port=5000)

#################################
# Main Entry
#################################
if __name__ == "__main__":
    if not os.path.exists(DATA_FILE):
        save_data({})
        logging.info("Created initial data file.")

    flask_thread = Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Initial scraping
    perform_scraping()

    # Schedule scraping every SCRAPE_INTERVAL minutes
    scheduler = BackgroundScheduler()
    scheduler.add_job(perform_scraping, 'interval', minutes=SCRAPE_INTERVAL)
    scheduler.start()
    logging.info(f"Scheduler started. Running every {SCRAPE_INTERVAL} minutes.")
    logging.info("Script running. Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logging.info("Script stopped.")
