#!/usr/bin/python3
import requests
from bs4 import BeautifulSoup
import os
import cv2
import pymongo
import img2pdf
from datetime import datetime
from urllib.parse import urljoin
import logging
import telegram
from telegram.ext import Updater, CommandHandler
from glob import glob
from tqdm import tqdm
import subprocess
import re

from config import MONGO_URI, DB_NAME, LOG_CHANNEL_ID, OWNER_ID, BOT_TOKEN

class MangaScraper:
    def __init__(self, log_file="manga_scraper.log"):
        logging.basicConfig(filename=log_file, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger()
        self.logger.info("MangaScraper initialized")
        self.client = pymongo.MongoClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        self.create_collections()
        self.bot = telegram.Bot(token=BOT_TOKEN)
        self.send_log_to_channel("MangaScraper initialized")
        self.updater = Updater(token=BOT_TOKEN, use_context=True)
        self.setup_handlers()
        self.install_mangadl()

    def create_collections(self):
        if "manga_downloads" not in self.db.list_collection_names():
            self.db.create_collection("manga_downloads")
        if "auth_users" not in self.db.list_collection_names():
            self.db.create_collection("auth_users")
        self.logger.info("MongoDB collections initialized")

    def send_log_to_channel(self, message):
        try:
            self.bot.send_message(chat_id=LOG_CHANNEL_ID, text=message)
            self.logger.info(f"Log sent to Telegram {LOG_CHANNEL_ID}: {message}")
        except Exception as e:
            self.logger.error(f"Failed to send log to Telegram: {e}")

    def add_auth_user(self, username, password, requester_id):
        if str(requester_id) != OWNER_ID:
            self.logger.warning(f"Unauthorized attempt to add user by {requester_id}")
            self.send_log_to_channel(f"Unauthorized attempt to add user by {requester_id}")
            return False
        user_data = {"username": username, "password": password}
        try:
            self.db.auth_users.insert_one(user_data)
            self.logger.info(f"New authorized user added: {username}")
            self.send_log_to_channel(f"New authorized user added: {username}")
            return True
        except pymongo.errors.DuplicateKeyError:
            self.logger.warning(f"Username '{username}' already exists")
            self.send_log_to_channel(f"Username '{username}' already exists")
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

    # Preprocess images with OpenCV (from new code)
    def preprocess_images(self, file_paths, apply_prog_bar=False):
        iterable = file_paths if not apply_prog_bar else tqdm(file_paths)
        for image_file in iterable:
            image = cv2.imread(image_file)
            os.remove(image_file)
            cv2.imwrite(image_file, image)

    # Install mangadl if not present (from new code)
    def install_mangadl(self):
        try:
            subprocess.check_output(["mangadl"])
        except:
            self.logger.info("Installing mangadl")
            self.send_log_to_channel("Installing mangadl")
            os.system(
                "curl --compressed -s https://raw.githubusercontent.com/Akianonymus/mangadl-bash/master/release/install | bash -s"
            )
            self.logger.info("mangadl installed")
            self.send_log_to_channel("mangadl installed")

    # Download and process for mangahindisub.in (original functionality)
    def download_hindisub(self, url, output_pdf_name):
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        self.logger.info(f"Attempting to access URL: {url}")
        self.send_log_to_channel(f"Attempting to access URL: {url}")
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            self.logger.error(f"Failed to get response from {url}. Status code: {response.status_code}")
            self.send_log_to_channel(f"Failed to get response from {url}")
            return False
        soup = BeautifulSoup(response.content, 'html.parser')
        img_tags = soup.find_all('img', class_=re.compile('wp-manga-chapter-img|img-responsive|lazyload'))
        if not img_tags:
            self.logger.warning(f"No manga images found on {url}")
            self.send_log_to_channel(f"No manga images found on {url}")
            return False
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
                else:
                    self.logger.warning(f"Failed to download {img_url}. Status code: {img_response.status_code}")
                    self.send_log_to_channel(f"Failed to download {img_url}")
            except Exception as e:
                self.logger.error(f"Error downloading {img_url}: {e}")
                self.send_log_to_channel(f"Error downloading {img_url}: {e}")
        if image_paths:
            self.logger.info(f"Preprocessing images for {output_pdf_name}")
            self.send_log_to_channel(f"Preprocessing images for {output_pdf_name}")
            self.preprocess_images(image_paths)
            self.logger.info(f"Creating PDF: {output_pdf_name}")
            self.send_log_to_channel(f"Creating PDF: {output_pdf_name}")
            with open(output_pdf_name, "wb") as f:
                f.write(img2pdf.convert(image_paths))
            self.logger.info(f"PDF created: {output_pdf_name}")
            self.send_log_to_channel(f"PDF created: {output_pdf_name}")
            self.add_download(url, output_pdf_name)
            for img_path in image_paths:
                os.remove(img_path)
                self.logger.info(f"Deleted temporary file: {img_path}")
                self.send_log_to_channel(f"Deleted temporary file: {img_path}")
            os.rmdir(temp_folder)
            self.logger.info(f"Deleted temporary folder: {temp_folder}")
            self.send_log_to_channel(f"Deleted temporary folder: {temp_folder}")
            return True
        else:
            self.logger.warning("No images downloaded, PDF not created")
            self.send_log_to_channel("No images downloaded, PDF not created")
            return False

    # Download and process using mangadl (new functionality)
    def download_mangadl(self, url, output_pdf_name):
        pdf_location = "./dump"
        if not os.path.isdir(pdf_location):
            os.makedirs(pdf_location)
            self.logger.info(f"Created dump folder: {pdf_location}")
            self.send_log_to_channel(f"Created dump folder: {pdf_location}")

        self.logger.info(f"Downloading manga from {url} using mangadl")
        self.send_log_to_channel(f"Downloading manga from {url} using mangadl")
        subprocess.run(["mangadl", url, "-d", "./dump"])

        chapters = sorted(glob("dump/*/*"), key=lambda x: float(x.split('/')[-1].split('.')[0]))
        if not chapters:
            self.logger.warning(f"No chapters found for {url}")
            self.send_log_to_channel(f"No chapters found for {url}")
            return False
        
        comic_name = chapters[0].split("/")[-2]
        all_image_files = []
        for chapter in chapters:
            image_files = sorted(
                glob(os.path.join(chapter, "*.jpg")),
                key=lambda x: float(x.split('/')[-1].split('.')[0])
            )
            all_image_files += image_files

        if all_image_files:
            self.logger.info("Preprocessing all images...")
            self.send_log_to_channel("Preprocessing all images...")
            self.preprocess_images(all_image_files, apply_prog_bar=True)
            self.logger.info(f"Compiling PDF: {output_pdf_name}")
            self.send_log_to_channel(f"Compiling PDF: {output_pdf_name}")
            with open(output_pdf_name, "wb") as f:
                f.write(img2pdf.convert(all_image_files))
            self.logger.info(f"PDF created: {output_pdf_name}")
            self.send_log_to_channel(f"PDF created: {output_pdf_name}")
            self.add_download(url, output_pdf_name)
            os.system(f"rm -rf './dump/{comic_name}'")
            self.logger.info(f"Cleaned up dump folder for {comic_name}")
            self.send_log_to_channel(f"Cleaned up dump folder for {comic_name}")
            return True
        else:
            self.logger.warning("No images downloaded, PDF not created")
            self.send_log_to_channel("No images downloaded, PDF not created")
            return False

    def close(self):
        self.client.close()
        self.logger.info("MongoDB connection closed")
        self.send_log_to_channel("Connections closed")

    # Telegram Bot Handlers
    def start(self, update, context):
        update.message.reply_text("Welcome to MangaScraper Bot! Use /add_auth <username> <password>, /download_hindisub <url> <pdf_name>, or /download_mangadl <url> <pdf_name>")

    def add_auth(self, update, context):
        user_id = str(update.message.from_user.id)
        if len(context.args) != 2:
            update.message.reply_text("Usage: /add_auth <username> <password>")
            return
        username, password = context.args
        if self.add_auth_user(username, password, user_id):
            update.message.reply_text(f"User '{username}' added successfully!")
        else:
            update.message.reply_text("Failed to add user. Check logs or permissions.")

    def download_hindisub_handler(self, update, context):
        user_id = str(update.message.from_user.id)
        if len(context.args) != 2:
            update.message.reply_text("Usage: /download_hindisub <url> <pdf_name>")
            return
        url, pdf_name = context.args
        if not pdf_name.endswith('.pdf'):
            pdf_name += '.pdf'
        auth_users = self.get_auth_users()
        if not auth_users:
            update.message.reply_text("No authorized users found. Add a user first with /add_auth.")
            return
        if user_id != OWNER_ID and user_id not in [str(u) for u in auth_users.keys()]:
            update.message.reply_text("You are not authorized to download.")
            return
        if self.download_hindisub(url, pdf_name):
            update.message.reply_text(f"PDF '{pdf_name}' created successfully!")
        else:
            update.message.reply_text("Failed to download or create PDF. Check logs.")

    def download_mangadl_handler(self, update, context):
        user_id = str(update.message.from_user.id)
        if len(context.args) != 2:
            update.message.reply_text("Usage: /download_mangadl <url> <pdf_name>")
            return
        url, pdf_name = context.args
        if not pdf_name.endswith('.pdf'):
            pdf_name += '.pdf'
        auth_users = self.get_auth_users()
        if not auth_users:
            update.message.reply_text("No authorized users found. Add a user first with /add_auth.")
            return
        if user_id != OWNER_ID and user_id not in [str(u) for u in auth_users.keys()]:
            update.message.reply_text("You are not authorized to download.")
            return
        if self.download_mangadl(url, pdf_name):
            update.message.reply_text(f"PDF '{pdf_name}' created successfully!")
        else:
            update.message.reply_text("Failed to download or create PDF. Check logs.")

    def setup_handlers(self):
        dp = self.updater.dispatcher
        dp.add_handler(CommandHandler("start", self.start))
        dp.add_handler(CommandHandler("add_auth", self.add_auth))
        dp.add_handler(CommandHandler("download_hindisub", self.download_hindisub_handler))
        dp.add_handler(CommandHandler("download_mangadl", self.download_mangadl_handler))
        self.updater.start_polling()

if __name__ == "__main__":
    scraper = MangaScraper()
    scraper.updater.idle()
    scraper.close()
