import requests
from bs4 import BeautifulSoup
import os
import pymongo
from datetime import datetime
import img2pdf
from urllib.parse import urljoin
import logging
import getpass
import sys
import re
from config import MONGO_URI, DB_NAME, LOG_CHANNEL_ID, OWNER_ID, API_ID, API_HASH
from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError

class MangaScraper:
    def __init__(self, log_file="manga_scraper.log", session_name="manga_session"):
        logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger()
        self.logger.info("MangaScraper initialized")
        self.client = pymongo.MongoClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        self.create_collections()
        self.telegram_client = TelegramClient(session_name, API_ID, API_HASH)
        self.start_telegram_client()

    def start_telegram_client(self):
        self.telegram_client.start()
        if not self.telegram_client.is_user_authorized():
            phone = input("Enter your phone number (e.g., +91XXXXXXXXXX): ")
            self.telegram_client.send_code_request(phone)
            try:
                self.telegram_client.sign_in(phone, input("Enter the code you received: "))
            except SessionPasswordNeededError:
                self.telegram_client.sign_in(password=getpass.getpass("Enter your 2FA password: "))
        self.logger.info("Telegram client started")
        self.send_log_to_channel("MangaScraper initialized and Telegram client started")

    def create_collections(self):
        if "manga_downloads" not in self.db.list_collection_names():
            self.db.create_collection("manga_downloads")
        if "auth_users" not in self.db.list_collection_names():
            self.db.create_collection("auth_users")
        self.logger.info("MongoDB collections initialized")

    def send_log_to_channel(self, message):
        try:
            self.telegram_client.send_message(int(LOG_CHANNEL_ID), message)
            self.logger.info(f"Log sent to Telegram {LOG_CHANNEL_ID}: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send log to Telegram: {e}")
            print(f"Failed to send log to Telegram: {e}")

    def add_auth_user(self, username, password, requester_id=None):
        if requester_id != OWNER_ID:
            self.logger.warning(f"Unauthorized attempt to add user by {requester_id}")
            self.send_log_to_channel(f"Unauthorized attempt to add user by {requester_id}")
            print("Only the owner can add new users.")
            return False
        user_data = {"username": username, "password": password}
        try:
            self.db.auth_users.insert_one(user_data)
            self.logger.info(f"New authorized user added: {username}")
            self.send_log_to_channel(f"New authorized user added: {username}")
            print(f"User '{username}' added successfully!")
            return True
        except pymongo.errors.DuplicateKeyError:
            self.logger.warning(f"Username '{username}' already exists")
            self.send_log_to_channel(f"Username '{username}' already exists")
            print(f"Username '{username}' already exists. Try a different username.")
            return False

    def get_auth_users(self):
        users = self.db.auth_users.find()
        return {user["username"]: user["password"] for user in users}

    def add_download(self, url, pdf_name):
        download_data = {
            "url": url,
            "pdf_name": pdf_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.db.manga_downloads.insert_one(download_data)
        self.logger.info(f"Added to database: {url} -> {pdf_name}")
        self.send_log_to_channel(f"Added to database: {url} -> {pdf_name}")
        print(f"Added to database: {url} -> {pdf_name}")

    def get_all_downloads(self):
        return list(self.db.manga_downloads.find())

    def authenticate(self):
        auth_users = self.get_auth_users()
        if not auth_users:
            self.logger.warning("No authorized users found. Add users using /add_auth")
            self.send_log_to_channel("No authorized users found")
            print("No authorized users found. Please add a user first using /add_auth.")
            return None
        attempts = 3
        while attempts > 0:
            username = input("Enter username: ")
            password = getpass.getpass("Enter password: ")
            if username in auth_users and auth_users[username] == password:
                self.logger.info(f"User '{username}' authenticated successfully")
                self.send_log_to_channel(f"User '{username}' authenticated successfully")
                print("Authentication successful!")
                return username
            else:
                attempts -= 1
                self.logger.warning(f"Authentication failed for user '{username}'. Attempts left: {attempts}")
                self.send_log_to_channel(f"Authentication failed for '{username}'. Attempts left: {attempts}")
                print(f"Wrong username or password. {attempts} attempts left.")
        self.logger.error("Authentication failed: Max attempts reached")
        self.send_log_to_channel("Authentication failed: Max attempts reached")
        print("Too many failed attempts. Access denied.")
        return None

    def download_images_to_pdf(self, url, output_pdf_name):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        self.logger.info(f"Attempting to access URL: {url}")
        self.send_log_to_channel(f"Attempting to access URL: {url}")
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            self.logger.error(f"Failed to get response from {url}. Status code: {response.status_code}")
            self.send_log_to_channel(f"Failed to get response from {url}")
            print("URL se response nahi mila. Check kar link sahi hai ya nahi.")
            return
        soup = BeautifulSoup(response.content, 'html.parser')
        img_tags = soup.find_all('img', class_=re.compile('wp-manga-chapter-img|img-responsive|lazyload'))
        if not img_tags:
            self.logger.warning(f"No manga images found on {url}")
            self.send_log_to_channel(f"No manga images found on {url}")
            print("Koi manga images nahi mili webpage pe.")
            return
        temp_folder = "temp_images"
        if not os.path.exists(temp_folder):
            os.makedirs(temp_folder)
            self.logger.info(f"Created temporary folder: {temp_folder}")
            self.send_log_to_channel(f"Created temporary folder: {temp_folder}")
        image_paths = []
        base_url = url
        for idx, img in enumerate(img_tags):
            img_url = img.get('src') or img.get('data-src')
            if not img_url:
                continue
            img_url = urljoin(base_url, img_url)
            try:
                self.logger.info(f"Downloading image: {img_url}")
                self.send_log_to_channel(f"Downloading image: {img_url}")
                img_response = requests.get(img_url, headers=headers)
                if img_response.status_code == 200:
                    img_path = os.path.join(temp_folder, f"image_{idx}.jpg")
                    with open(img_path, 'wb') as f:
                        f.write(img_response.content)
                    image_paths.append(img_path)
                    self.logger.info(f"Successfully downloaded: {img_url}")
                    self.send_log_to_channel(f"Successfully downloaded: {img_url}")
                    print(f"Downloaded: {img_url}")
                else:
                    self.logger.warning(f"Failed to download {img_url}. Status code: {img_response.status_code}")
                    self.send_log_to_channel(f"Failed to download {img_url}")
                    print(f"Failed to download: {img_url}")
            except Exception as e:
                self.logger.error(f"Error downloading {img_url}: {e}")
                self.send_log_to_channel(f"Error downloading {img_url}: {e}")
                print(f"Error downloading {img_url}: {e}")
        if image_paths:
            self.logger.info(f"Creating PDF: {output_pdf_name}")
            self.send_log_to_channel(f"Creating PDF: {output_pdf_name}")
            print("PDF banaya ja raha hai...")
            with open(output_pdf_name, "wb") as f:
                f.write(img2pdf.convert(image_paths))
            self.logger.info(f"PDF created: {output_pdf_name}")
            self.send_log_to_channel(f"PDF created: {output_pdf_name}")
            print(f"PDF ban gaya: {output_pdf_name}")
            self.add_download(url, output_pdf_name)
            for img_path in image_paths:
                os.remove(img_path)
                self.logger.info(f"Deleted temporary file: {img_path}")
                self.send_log_to_channel(f"Deleted temporary file: {img_path}")
            os.rmdir(temp_folder)
            self.logger.info(f"Deleted temporary folder: {temp_folder}")
            self.send_log_to_channel(f"Deleted temporary folder: {temp_folder}")
        else:
            self.logger.warning("No images downloaded, PDF not created")
            self.send_log_to_channel("No images downloaded, PDF not created")
            print("Koi image download nahi hui, PDF nahi banega.")

    def close(self):
        self.telegram_client.disconnect()
        self.client.close()
        self.logger.info("MongoDB and Telegram connections closed")
        self.send_log_to_channel("Connections closed")

if __name__ == "__main__":
    scraper = MangaScraper()
    if len(sys.argv) > 1:
        if sys.argv[1] == "/add_auth":
            if len(sys.argv) != 4:
                print("Usage: python mangahindisub_scraper.py /add_auth <username> <password>")
                scraper.close()
                exit()
            username = sys.argv[2]
            password = sys.argv[3]
            authenticated_user = scraper.authenticate()
            if authenticated_user:
                scraper.add_auth_user(username, password, authenticated_user)
            scraper.close()
            exit()
        elif sys.argv[1] == "/download":
            if len(sys.argv) < 3 or "-n" not in sys.argv:
                print("Usage: python mangahindisub_scraper.py /download <url> -n <new_file_name>")
                scraper.close()
                exit()
            url = sys.argv[2]
            authenticated_user = scraper.authenticate()
            if not authenticated_user:
                scraper.close()
                exit()
            new_file_name_idx = sys.argv.index("-n") + 1
            if new_file_name_idx >= len(sys.argv):
                print("Please provide a new file name after -n")
                scraper.close()
                exit()
            new_file_name = sys.argv[new_file_name_idx]
            if not new_file_name.endswith('.pdf'):
                new_file_name += '.pdf'
            scraper.download_images_to_pdf(url, new_file_name)
            scraper.close()
            exit()
    authenticated_user = scraper.authenticate()
    if not authenticated_user:
        scraper.close()
        exit()
    manga_url = input("Manga page ka URL daal: ")
    pdf_name = input("PDF ka naam kya rakhna hai (e.g., manga.pdf): ")
    if not pdf_name.endswith('.pdf'):
        pdf_name += '.pdf'
    scraper.download_images_to_pdf(manga_url, pdf_name)
    downloads = scraper.get_all_downloads()
    print("\nDatabase mein entries:")
    for download in downloads:
        print(f"ID: {download['_id']}, URL: {download['url']}, PDF: {download['pdf_name']}, Time: {download['timestamp']}")
    scraper.close()
