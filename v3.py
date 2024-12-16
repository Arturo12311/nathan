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
import subprocess
from selenium.common.exceptions import WebDriverException

#################################
# Configuration
#################################
SCRAPE_INTERVAL = 15  # minutes
LINKS_FILE = 'links.json'
DATA_FILE = 'data.json'
LOG_FILE = 'scraper.log'

SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_ADDRESS = 'sdffd9327@gmail.com'
EMAIL_PASSWORD = 'stpz lxgn fpiq uucs '
RECIPIENTS = [
    'sdffd9327@gmail.com',
    'nanabitbol@gmail.com'
]

MAX_URL_RETRIES = 3  # Max attempts per URL to load

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
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = uc.Chrome(options=options)
    return driver

def fallback_name_from_url(url):
    segment = url.split('/')[-1]
    segment = segment.split('?')[0]
    name = re.sub(r'[-_]', ' ', segment)
    return name.strip().title() if name.strip() else "Unknown Product"

def wait_for_price(driver, xpath, max_tries=3):
    wait = WebDriverWait(driver, 10)
    for _ in range(max_tries):
        try:
            elem = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
            text = elem.text.strip()
            if text and text != "--":
                return text
            time.sleep(3)
        except:
            time.sleep(3)
    return None

def extract_name_generic(driver):
    candidates = [
        "//h1",
        "//h1[@data-automation='product-title']",
        "//span[@id='productTitle']"
    ]
    for xp in candidates:
        try:
            elem = driver.find_element(By.XPATH, xp)
            if elem.text.strip():
                return elem.text.strip()
        except:
            continue
    if driver.title and driver.title.strip():
        return driver.title.strip()
    return None

#################################
# Restart logic if browser hangs
#################################
driver = None

def force_restart_driver():
    global driver
    logging.error("Forcing browser termination and restarting driver...")
    try:
        if driver:
            driver.quit()
    except:
        pass
    # kill any leftover processes
    try:
        subprocess.run(["pkill", "-f", "chromedriver"], check=False)
        subprocess.run(["pkill", "-f", "chrome"], check=False)
    except Exception as e:
        logging.error(f"Failed to kill chrome processes: {e}")

    time.sleep(5)
    driver = get_driver(headless=False)
    logging.info("Driver reinitialized after forced termination.")

def safe_get_url(url, max_attempts=3):
    global driver
    for attempt in range(1, max_attempts+1):
        logging.info(f"Attempting to load URL: {url} (Attempt {attempt}/{max_attempts})")
        try:
            driver.get(url)
            return True
        except Exception as e:
            logging.warning(f"Error loading {url}: {e}. Attempting driver restart...")
            force_restart_driver()
    logging.error(f"Failed to load {url} after {max_attempts} attempts.")
    return False

#################################
# Extractor
#################################
def extract_info_walmart(url):
    global driver
    # We'll retry the entire extraction if it fails
    for attempt in range(1, MAX_URL_RETRIES+1):
        try:
            if not safe_get_url(url, max_attempts=3):
                logging.info(f"No update for {url} due to browser issues after all attempts.")
                return None

            page_source = driver.page_source
            if "We like real shoppers, not robots" in page_source:
                # Bot detection, return error but do not update data
                logging.info(f"Bot detection encountered for {url}. Returning error state.")
                return {'name': fallback_name_from_url(url), 'price': None, 'availability': 'Error', 'error': 'Bot detection'}

            name = extract_name_generic(driver) or fallback_name_from_url(url)

            availability = 'Error'
            price = None

            # Check out of stock
            if "Out of stock" in page_source:
                availability = 'OutOfStock'
            else:
                # Try to find price
                price_xpaths = [
                    "//span[@itemprop='price']",
                    "//span[contains(@class, 'price')]",
                    "//div[@class='price-section']//span[@class='value']"
                ]
                for xp in price_xpaths:
                    found_price_text = wait_for_price(driver, xp, max_tries=3)
                    if found_price_text:
                        try:
                            price = float(found_price_text.replace('$', '').replace(',', '').strip())
                            availability = 'InStock'
                            break
                        except:
                            pass

            # Log price and availability extracted
            logging.info(f"For URL {url}: Extracted Price={price}, Availability={availability}")

            # If we fail to get both price and availability meaningfully, we return None
            # This ensures no erroneous notifications or updates
            if availability == 'Error' and price is None:
                logging.info(f"No meaningful data from {url}, returning None.")
                return None

            return {
                'name': name,
                'price': price,
                'availability': availability
            }

        except WebDriverException as e:
            logging.error(f"WebDriverException scraping Walmart {url} (attempt {attempt}/{MAX_URL_RETRIES}): {e}", exc_info=True)
            force_restart_driver()
        except Exception as e:
            logging.error(f"Unexpected error scraping Walmart {url} (attempt {attempt}/{MAX_URL_RETRIES}): {e}", exc_info=True)
            force_restart_driver()

    # If we got here, we failed all attempts
    logging.error(f"All {MAX_URL_RETRIES} attempts failed for {url}. Returning None without updates.")
    return None

#################################
# Main Scraping Logic
#################################
def perform_scraping():
    logging.info("Starting scrape cycle.")
    links = load_links()
    existing_data = load_existing_data()

    global driver
    if driver is None:
        logging.info("Initializing driver once.")
        driver = get_driver(headless=False)

    updated_data = existing_data.copy()
    change_count = 0
    notification_count = 0

    for item in links:
        site = item.get('site')
        url = item.get('url')
        if not site or not url:
            logging.warning(f"Invalid link entry: {item}")
            continue

        data = None
        try:
            if 'walmart' in site.lower():
                data = extract_info_walmart(url)
            else:
                data = None

            # If data is None or error state with no improvement, do not send notification/update
            if data is None:
                logging.info(f"No data or incomplete data for {url}, skipping updates and notifications.")
                continue

            prev_data = updated_data.get(url, {})
            old_price = prev_data.get('price')
            old_avail = prev_data.get('availability')
            new_price = data.get('price')
            new_avail = data.get('availability')

            # If error state and previously it was good or vice versa
            # We'll only send notification if we have a meaningful change
            # If it's an Error state, let's not send notifications as requested.
            if new_avail == 'Error':
                # Just log that we got an error, do not send notification or update data.
                logging.info(f"Got an error state for {url} with no stable data. No update, no notification.")
                continue

            # Now we have a stable InStock/OutOfStock scenario
            data['site'] = site
            change_detected = False
            notification_body = ""

            if prev_data:
                # Compare old and new
                if old_price != new_price or old_avail != new_avail:
                    change_detected = True
                    notification_body += (
                        f"Product: {data.get('name','N/A')}\n"
                        f"URL: {url}\n"
                        f"Old Price: {old_price}\n"
                        f"New Price: {new_price}\n"
                        f"Old Availability: {old_avail}\n"
                        f"New Availability: {new_avail}\n\n"
                    )
            else:
                # New product entirely
                change_detected = True
                notification_body += (
                    f"Product: {data.get('name','N/A')}\n"
                    f"URL: {url}\n"
                    f"Price: {new_price}\n"
                    f"Availability: {new_avail}\n\n"
                )

            updated_data[url] = data
            save_data(updated_data)

            if change_detected and notification_body.strip():
                subject = "Stock Change Detected"
                send_email(subject, notification_body)
                notification_count += 1
                change_count += 1

        except Exception as e:
            # On any exception, we log and restart the driver, no updates/no notifications
            logging.error(f"Error processing {url}: {e}", exc_info=True)
            force_restart_driver()
            continue

    logging.info(f"Cycle completed: {change_count} changes, {notification_count} notifications.")
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
        if driver is not None:
            driver.quit()
        scheduler.shutdown()
        logging.info("Script stopped.")
