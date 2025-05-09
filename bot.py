import discord
from discord.ext import commands, tasks
import json
import aiohttp
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import os
from discord import ButtonStyle
from discord.ui import Button, View
import logging
import asyncio
import random

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8000))

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
        return {"stores": {}, "items": {}, "channel_id": None}

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

# Button-based UI
class StockBotView(View):
    async def send_embed(self, channel):
        embed = discord.Embed(
            title="StockBot Setup",
            description="Type `/setup` in #stock-alerts to start. Use the buttons below to manage stores and items. Stock alerts will ping @everyone in this channel. **Note**: Slash commands like `/additem` are not supported; use the buttons.",
            color=discord.Color.blue()
        )
        await channel.send(embed=embed, view=self)

    @discord.ui.button(label="Add Store", style=ButtonStyle.green)
    async def add_store(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Please provide the store name and URL (e.g., `Pokemon Center UK, https://uk.pokemoncenter.com`):", ephemeral=True)
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            name, url = map(str.strip, msg.content.split(',', 1))
            config['stores'][name] = url
            save_config(config)
            await interaction.followup.send(f"Added store: {name} ({url})", ephemeral=True)
        except:
            await interaction.followup.send("Invalid format or timeout. Use: `name, url`", ephemeral=True)

    @discord.ui.button(label="Add Item", style=ButtonStyle.green)
    async def add_item(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Please provide the item name, URL, and store name (e.g., `Prismatic Evolutions ETB, https://uk.pokemoncenter.com/product/..., Pokemon Center UK`):", ephemeral=True)
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            name, url, store = map(str.strip, msg.content.split(',', 2))
            if store not in config['stores']:
                await interaction.followup.send(f"Store '{store}' not found.", ephemeral=True)
                return
            config['items'][name] = {'url': url, 'store': store, 'last_status': None, 'last_low_stock': None}
            save_config(config)
            await interaction.followup.send(f"Added item: {name} ({url}) for {store}", ephemeral=True)
        except:
            await interaction.followup.send("Invalid format or timeout. Use: `name, url, store`", ephemeral=True)

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
            await interaction.followup.send("Timeout.", ephemeral=True)

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
                interaction.followup.send(f"Item '{name}' not found.", ephemeral=True)
        except:
            await interaction.followup.send("Timeout.", ephemeral=True)

    @discord.ui.button(label="Check Stock Now", style=ButtonStyle.blurple)
    async def check_stock(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)
        results = await check_all_stock()
        channel = bot.get_channel(int(config['channel_id']))
        for result in results:
            await channel.send(embed=result)
        await interaction.followup.send("Stock check completed.", ephemeral=True)

# Stock checking logic
async def check_stock(url, store):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()
        try:
            # Navigate with timeout and wait for dynamic content
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(random.randint(2000, 5000))  # Random delay for anti-bot

            # Check for CAPTCHA
            captcha = await page.query_selector('text="Enter the characters you see below"')
            if captcha:
                logger.error(f"CAPTCHA detected on {url}")
                return False, "Blocked by CAPTCHA", None, False

            # Define stock status terms
            in_stock_terms = [
                "in stock", "available to ship", "add to cart", "buy now",
                "get it by", "arrives before", "free delivery", "pre-order now",
                "available from", "ships from and sold by amazon.co.uk"
            ]
            low_stock_terms = [f"only {i} left in stock" for i in range(1, 16)]
            low_stock_terms.extend([f"only {i} left in stock (more on the way)" for i in range(1, 16)])
            in_stock_terms.extend(low_stock_terms)

            out_of_stock_terms = [
                "currently unavailable", "out of stock", "temporarily out of stock",
                "we don’t know when or if this item will be back in stock",
                "see all buying options"
            ]

            # Store-specific checks
            if store == "Pokemon Center UK":
                stock_element = await page.query_selector('button.add-to-cart')
                is_in_stock = bool(stock_element)
                reason = "Add to Cart button found" if is_in_stock else "No Add to Cart button"
                image_elem = await page.query_selector('img.product-image')
                image_url = await image_elem.get_attribute('src') if image_elem else None
                is_low_stock = False
            elif store == "Smyths Toys":
                stock_element = await page.query_selector('text=In Stock')
                is_in_stock = bool(stock_element)
                reason = "In Stock text found" if is_in_stock else "No In Stock text"
                image_elem = await page.query_selector('img[data-main-image]')
                image_url = await image_elem.get_attribute('src') if image_elem else None
                is_low_stock = False
            else:  # Amazon UK
                # Check availability div
                availability = await page.query_selector("#availability")
                availability_text = await availability.inner_text() if availability else ""
                availability_text = availability_text.lower()

                # Check buttons
                add_to_cart = await page.query_selector("#add-to-cart-button")
                buy_now = await page.query_selector("#buy-now-button")

                # Check delivery message
                delivery = await page.query_selector("#deliveryBlockMessage")
                delivery_text = await delivery.inner_text() if delivery else ""

                # Check seller
                seller = await page.query_selector("#merchant-info")
                seller_text = await seller.inner_text() if seller else ""
                is_amazon_seller = "amazon" in seller_text.lower() or "ships from and sold by amazon.co.uk" in availability_text

                # Determine stock status
                is_in_stock = False
                is_low_stock = False
                reason = "Unknown"

                if add_to_cart or buy_now:
                    is_in_stock = True
                    reason = "Add to Cart or Buy Now button found"
                elif any(term in availability_text for term in in_stock_terms) or \
                     any(term in delivery_text.lower() for term in in_stock_terms):
                    is_in_stock = True
                    reason = f"In stock text found: {availability_text[:50]}..."
                elif any(term in availability_text for term in out_of_stock_terms):
                    is_in_stock = False
                    reason = "Out of stock text found"
                elif not availability_text and not add_to_cart and not buy_now:
                    is_in_stock = False
                    reason = "No stock indicators found"

                # Check low stock
                if is_in_stock and any(term in availability_text for term in low_stock_terms):
                    is_low_stock = True
                    reason = f"Low stock: {availability_text[:50]}..."

                # Prefer Amazon direct stock
                if is_in_stock and not is_amazon_seller:
                    is_in_stock = False
                    is_low_stock = False
                    reason = "In stock by third-party seller, not Amazon"

                # Get product image
                image_elem = await page.query_selector("img#landingImage")
                image_url = await image_elem.get_attribute("src") if image_elem else None

            await browser.close()
            return is_in_stock, reason, image_url, is_low_stock
        except Exception as e:
            logger.error(f"Error checking {url}: {str(e)}")
            await browser.close()
            return False, f"Error: {str(e)}", None, False

async def check_all_stock():
    results = []
    for item_name, item_data in config['items'].items():
        url = item_data['url']
        store = item_data['store']
        last_status = item_data.get('last_status')
        last_low_stock = item_data.get('last_low_stock')
        is_in_stock, reason, image_url, is_low_stock = await check_stock(url, store)

        # Notify for in-stock or low-stock changes
        if is_in_stock:
            title = f"{item_name} is IN STOCK at {store}!"
            if is_low_stock:
                title = f"{item_name} LOW STOCK at {store}! ({reason})"
            if (last_status != "in_stock" or (is_low_stock and last_low_stock != True)):
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
        elif last_status != "out_of_stock":
            config['items'][item_name]['last_status'] = "out_of_stock"
            config['items'][item_name]['last_low_stock'] = False

        save_config(config)
    return results

# Periodic stock checker
@tasks.loop(seconds=60)
async def stock_checker():
    if not config['channel_id']:
        return
    channel = bot.get_channel(int(config['channel_id']))
    results = await check_all_stock()
    for result in results:
        await channel.send(content="@everyone", embed=result)

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
    stock_checker.start()

@bot.command()
async def setup(ctx):
    config['channel_id'] = str(ctx.channel.id)
    save_config(config)
    view = StockBotView()
    await view.send_embed(ctx.channel)
    await ctx.send("Setup complete! Use the buttons to manage stores and items.")

bot.run(DISCORD_TOKEN)