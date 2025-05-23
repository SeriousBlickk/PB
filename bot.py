import discord
from discord.ext import commands, tasks
import json
from playwright.async_api import async_playwright, Error as PlaywrightError
from dotenv import load_dotenv
import os
from discord import ButtonStyle
from discord.ui import Button, View, Modal, TextInput
import logging
import asyncio
import random

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8000))
PROXY_URL = os.getenv("PROXY_URL")  # Optional: e.g., "http://username:password@proxy:port"

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Load config
def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("config.json not found, creating a new one.")
        config = {"stores": {}, "items": {}, "channel_id": None}
        save_config(config)
        return config

def save_config(config):
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

config = load_config()

# Health endpoint for UptimeRobot
async def health_check():
    from aiohttp import web
    app = web.Application()
    async def health(request):
        return web.Response(text="Bot is running!")
    app.add_routes([web.get('/health', health)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# Modal for adding stores
class AddStoreModal(Modal, title="Add Store"):
    store_name = TextInput(label="Store Name", placeholder="e.g., Amazon UK", required=True)
    store_url = TextInput(label="Store URL", placeholder="e.g., https://www.amazon.co.uk", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.store_name.value.strip()
        url = self.store_url.value.strip()
        if not name or not url:
            await interaction.response.send_message("Both fields are required.", ephemeral=True)
            return
        config['stores'][name] = url
        save_config(config)
        await interaction.response.send_message(f"Added store: {name} ({url})", ephemeral=True)

# Modal for adding items
class AddItemModal(Modal, title="Add Item"):
    item_name = TextInput(label="Item Name", placeholder="e.g., Prismatic Evolutions ETB", required=True)
    item_url = TextInput(label="Item URL", placeholder="e.g., https://www.amazon.co.uk/product/...", required=True)
    store_name = TextInput(label="Store Name", placeholder="e.g., Amazon UK", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.item_name.value.strip()
        url = self.item_url.value.strip()
        store = self.store_name.value.strip()
        if not name or not url or not store:
            await interaction.response.send_message("All fields are required.", ephemeral=True)
            return
        if store not in config['stores']:
            await interaction.response.send_message(f"Store '{store}' not found. Add it first.", ephemeral=True)
            return
        config['items'][name] = {'url': url, 'store': store, 'last_status': None, 'last_low_stock': None}
        save_config(config)
        await interaction.response.send_message(f"Added item: {name} ({url}) for {store}", ephemeral=True)

# Button-based UI
class StockBotView(View):
    async def send_embed(self, channel):
        embed = discord.Embed(
            title="StockBot Setup",
            description="Type `/setup` in #stock-alerts to start. Use the buttons below to manage stores and items. Stock alerts will ping @everyone in this channel.",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed, view=self)

    @discord.ui.button(label="Add Store", style=ButtonStyle.green)
    async def add_store(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddStoreModal())

    @discord.ui.button(label="Add Item", style=ButtonStyle.green)
    async def add_item(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddItemModal())

    @discord.ui.button(label="Remove Store", style=ButtonStyle.red)
    async def remove_store(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Please provide the store name to remove:", ephemeral=True)
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            name = msg.content.strip()
            if name in config['stores']:
                del config['stores'][name]
                config['items'] = {k: v for k, v in config['items'].items() if v['store'] != name}
                save_config(config)
                await interaction.followup.send(f"Removed store: {name}", ephemeral=True)
            else:
                await interaction.followup.send(f"Store '{name}' not found.", ephemeral=True)
        except:
            await interaction.followup.send("Timeout. Please try again.", ephemeral=True)

    @discord.ui.button(label="Remove Item", style=ButtonStyle.red)
    async def remove_item(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Please provide the item name to remove:", ephemeral=True)
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            name = msg.content.strip()
            if name in config['items']:
                del config['items'][name]
                save_config(config)
                await interaction.followup.send(f"Removed item: {name}", ephemeral=True)
            else:
                await interaction.followup.send(f"Item '{name}' not found.", ephemeral=True)
        except:
            await interaction.followup.send("Timeout. Please try again.", ephemeral=True)

    @discord.ui.button(label="Check Stock Now", style=ButtonStyle.blurple)
    async def check_stock(self, interaction: discord.Interaction, button: Button):
        logger.info("Check Stock Now button clicked.")
        # Defer immediately to avoid timeout
        try:
            await interaction.response.defer(ephemeral=True)
            logger.info("Interaction deferred successfully.")
        except Exception as e:
            logger.error(f"Failed to defer interaction: {str(e)}")
            return

        if not config['channel_id']:
            logger.warning("No channel_id set in config.")
            await interaction.followup.send("Channel not set. Run `/setup` in #stock-alerts.", ephemeral=True)
            return
        channel = bot.get_channel(int(config['channel_id']))
        if not channel:
            logger.warning("Channel not found for channel_id: {config['channel_id']}")
            await interaction.followup.send("Channel not found. Run `/setup` in #stock-alerts.", ephemeral=True)
            return

        # Log config state
        logger.info(f"Config items: {config['items']}")

        # Run stock check in background
        try:
            results = await check_all_stock(manual=True)
            logger.info(f"Stock check completed with {len(results)} results.")
            if results:
                for result in results:
                    await channel.send(embed=result)
                await interaction.followup.send("Stock check completed.", ephemeral=True)
            else:
                await interaction.followup.send("No new stock updates. Check URLs or try again.", ephemeral=True)
        except Exception as e:
            logger.error(f"Check stock failed: {str(e)}")
            await interaction.followup.send("Failed to check stock due to an error. Please try again later.", ephemeral=True)

# Expanded user-agent pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

# Updated stock checking logic with Playwright
async def check_stock(url, store, retries=3):
    logger.info(f"Starting stock check for {url}")
    try:
        async with async_playwright() as p:
            # Configure proxy if provided
            proxy = None
            if PROXY_URL:
                logger.info(f"Using proxy for {url}: {PROXY_URL}")
                proxy = {"server": PROXY_URL}

            browser = await p.chromium.launch(headless=True, proxy=proxy)
            logger.info("Browser launched successfully.")
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1280, "height": 720},
                extra_http_headers={
                    "Accept-Language": "en-GB,en-US;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1"
                },
                java_script_enabled=True,
                locale="en-GB",
                geolocation={"latitude": 51.5074, "longitude": -0.1278},  # London coordinates
                permissions=["geolocation"]
            )
            logger.info("Browser context created successfully.")
            page = await context.new_page()

            for attempt in range(retries):
                try:
                    # Random delay to mimic human behavior
                    await asyncio.sleep(random.uniform(0.5, 2.0))

                    # Navigate with increased timeout and relaxed wait condition
                    try:
                        logger.info(f"Navigating to {url}, attempt {attempt + 1}")
                        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    except PlaywrightError as e:
                        if "Timeout" in str(e):
                            logger.warning(f"Timeout on {url}, attempt {attempt + 1}. Falling back to partial load check.")
                            # Fallback: Check if page loaded partially
                            title = await page.title()
                            if title:
                                logger.info(f"Page partially loaded for {url}: Title = {title}")
                            else:
                                raise e  # Re-raise if no content loaded

                    await page.wait_for_timeout(random.randint(3000, 5000))  # Wait for JS rendering

                    # Log page content for debugging
                    content = await page.content()
                    logger.debug(f"Page content for {url}: {content[:1000]}...")

                    # Check for CAPTCHA or bot detection
                    captcha = await page.query_selector('text="Enter the characters you see below"') or \
                              await page.query_selector('form[action*="/errors/validateCaptcha"]')
                    if captcha:
                        logger.warning(f"CAPTCHA detected on {url}, attempt {attempt + 1}")
                        if attempt < retries - 1:
                            await page.wait_for_timeout(random.randint(2000, 5000))
                            continue
                        await browser.close()
                        return None, "Blocked by CAPTCHA", None, False

                    title = await page.title()
                    if "sorry" in title.lower() or "robot" in title.lower():
                        logger.warning(f"Bot detection or redirect on {url}, attempt {attempt + 1}")
                        if attempt < retries - 1:
                            await page.wait_for_timeout(random.randint(2000, 5000))
                            continue
                        await browser.close()
                        return None, "Bot detection or redirect", None, False

                    # Check for 403 Forbidden (Pokémon Center)
                    if "403" in title or "Forbidden" in title:
                        logger.warning(f"403 Forbidden on {url}, attempt {attempt + 1}")
                        if attempt < retries - 1:
                            await page.wait_for_timeout(random.randint(2000, 5000))
                            continue
                        await browser.close()
                        return None, "403 Forbidden", None, False

                    # Store-specific checks
                    in_stock = await check_stock(page, url, store)  # Using the new check_stock function here
                    if in_stock:
                        reason = f"{store} - In stock detected"
                    else:
                        reason = f"{store} - Out of stock or failed to detect"

                    image_elem = await page.query_selector('img.product-image')
                    image_url = await image_elem.get_attribute('src') if image_elem else None
                    is_low_stock = False
                    await browser.close()
                    return in_stock, reason, image_url, is_low_stock

                except PlaywrightError as e:
                    logger.warning(f"Attempt {attempt + 1} failed for {url}: {str(e)}")
                    if attempt < retries - 1:
                        await page.wait_for_timeout(random.randint(2000, 5000))
                        continue
                    await browser.close()
                    return None, f"Error after retries: {str(e)}", None, False
                except Exception as e:
                    logger.error(f"Unexpected error checking {url}: {str(e)}")
                    await browser.close()
                    return None, f"Unexpected error: {str(e)}", None, False
    except Exception as e:
        logger.error(f"Failed to initialize Playwright for {url}: {str(e)}")
        return None, f"Playwright initialization failed: {str(e)}", None, False

async def check_all_stock(manual=False):
    logger.info("Starting check_all_stock")
    if not config['items']:
        logger.warning("No items configured to check.")
        return []

    results = []
    for item_name, item_data in config['items'].items():
        url = item_data['url']
        store = item_data['store']
        last_status = item_data.get('last_status')
        last_low_stock = item_data.get('last_low_stock')
        logger.info(f"Checking item: {item_name}, URL: {url}, Store: {store}")
        is_in_stock, reason, image_url, is_low_stock = await check_stock(url, store)

        # Skip if check failed (e.g., timeout, CAPTCHA)
        if is_in_stock is None:
            logger.info(f"Skipping notification for {item_name} due to: {reason}")
            continue

        # Notify for in-stock or low-stock
        if is_in_stock:
            title = f"{item_name} is IN STOCK at {store}!"
            if is_low_stock:
                title = f"{item_name} LOW STOCK at {store}! ({reason})"
            if manual or (last_status != "in_stock" or (is_low_stock and last_low_stock != True)):
                embed = discord.Embed(
                    title=title,
                    description=f"URL: {url}\nReason: {reason}",
                    color=discord.Color.green() if not is_low_stock else discord.Color.orange()
                )
                if image_url:
                    embed.set_image(url=image_url)
                embed.set_footer(text="PokemonStockBot")
                results.append(embed)
                config['items'][item_name]['last_status'] = "in_stock"
                config['items'][item_name]['last_low_stock'] = is_low_stock
        else:
            config['items'][item_name]['last_status'] = "out_of_stock"
            config['items'][item_name]['last_low_stock'] = False

        save_config(config)
    logger.info(f"check_all_stock completed with {len(results)} results")
    return results

# Periodic stock checker
@tasks.loop(seconds=60)
async def stock_checker():
    logger.info("Starting periodic stock checker")
    if not config['channel_id']:
        logger.warning("No channel_id set. Run `/setup` in #stock-alerts.")
        return
    channel = bot.get_channel(int(config['channel_id']))
    if not channel:
        logger.error("Channel not found. Run `/setup` in #stock-alerts.")
        return
    try:
        results = await check_all_stock(manual=False)
        if results:
            for result in results:
                await channel.send(content="@everyone", embed=result)
            logger.info(f"Sent {len(results)} stock alerts to channel {config['channel_id']}")
    except Exception as e:
        logger.error(f"Stock checker failed: {str(e)}")

# Bot events and commands
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    await health_check()
    if config['channel_id']:
        channel = bot.get_channel(int(config['channel_id']))
        if channel:
            view = StockBotView()
            await view.send_embed(channel)
            logger.info(f"Sent setup embed to channel {config['channel_id']}")
        else:
            logger.warning("Channel_id set but channel not found. Run `/setup`.")
    else:
        logger.warning("No channel_id set. Run `/setup` in #stock-alerts.")
    if not stock_checker.is_running():
        stock_checker.start()
        logger.info("Started stock checker task.")

@bot.command()
async def setup(ctx):
    logger.info(f"Running /setup in channel {ctx.channel.id}")
    config['channel_id'] = str(ctx.channel.id)
    save_config(config)
    view = StockBotView()
    await view.send_embed(ctx.channel)
    await ctx.send("Setup complete! Use the buttons to manage stores and items.")
    if not stock_checker.is_running():
        stock_checker.start()
        logger.info("Started stock checker task after setup.")

bot.run(DISCORD_TOKEN)