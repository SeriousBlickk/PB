import discord
from discord.ext import commands, tasks
from playwright.async_api import async_playwright
import aiohttp
from aiohttp import web
import json
import asyncio
import logging
from datetime import datetime
import os
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Initialize bot with intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Load/store config
CONFIG_FILE = 'config.json'

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        default_config = {'stores': {}, 'items': {}, 'channel_id': None}
        save_config(default_config)
        return default_config

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

# Initialize config
config = load_config()

# Stock checking logic with image extraction
async def check_stock(store, url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            stock_status = False
            image_url = None

            if store == 'Pokemon Center UK':
                stock_element = await page.query_selector('button.add-to-cart')
                stock_status = bool(stock_element)
                image_element = await page.query_selector('img.product-image')
                image_url = await image_element.get_attribute('src') if image_element else None

            elif store == 'Smyths Toys':
                stock_element = await page.query_selector('text=In Stock')
                stock_status = bool(stock_element)
                image_element = await page.query_selector('img[data-main-image]')
                image_url = await image_element.get_attribute('src') if image_element else None

            elif store == 'Amazon UK':
                stock_element = await page.query_selector('#add-to-cart-button')
                stock_status = bool(stock_element)
                image_element = await page.query_selector('#landingImage')
                image_url = await image_element.get_attribute('src') if image_element else None

            if image_url and not image_url.startswith('http'):
                image_url = f"https://{url.split('/')[2]}{image_url}"

            return stock_status, image_url

        except Exception as e:
            logger.error(f"Error checking {store}: {e}")
            return False, None
        finally:
            await browser.close()

# Background task to check stock
@tasks.loop(seconds=60)
async def stock_checker():
    if not config.get('channel_id'):
        return
    channel = bot.get_channel(int(config['channel_id']))
    if not channel:
        logger.error("Stock alerts channel not found!")
        return
    for item_name, item_data in config['items'].items():
        for store, url in item_data['stores'].items():
            in_stock, image_url = await check_stock(store, url)
            if in_stock:
                embed = discord.Embed(
                    title="Stock Alert!",
                    description=f"**{item_name}** is in stock at **{store}**!",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="URL", value=f"[Click Here]({url})", inline=False)
                if image_url:
                    embed.set_image(url=image_url)
                else:
                    embed.add_field(name="Note", value="Product image unavailable.", inline=False)
                await channel.send("@everyone", embed=embed)
                logger.info(f"Stock found for {item_name} at {store}")

# UI for managing bot
class StockBotView(discord.ui.View):
    @discord.ui.button(label="Add Store", style=discord.ButtonStyle.green)
    async def add_store(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddStoreModal())

    @discord.ui.button(label="Remove Store", style=discord.ButtonStyle.red)
    async def remove_store(self, interaction: discord.Interaction, button: discord.ui.Button):
        options = [discord.SelectOption(label=store) for store in config['stores'].keys()]
        if not options:
            await interaction.response.send_message("No stores to remove!", ephemeral=True)
            return
        select = discord.ui.Select(placeholder="Select a store to remove", options=options)
        async def select_callback(interaction):
            store = select.values[0]
            del config['stores'][store]
            for item in config['items'].values():
                if store in item['stores']:
                    del item['stores'][store]
            save_config(config)
            await interaction.response.send_message(f"Removed store: {store}", ephemeral=True)
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select a store to remove:", view=view, ephemeral=True)

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.green)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddItemModal())

    @discord.ui.button(label="Remove Item", style=discord.ButtonStyle.red)
    async def remove_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        options = [discord.SelectOption(label=item) for item in config['items'].keys()]
        if not options:
            await interaction.response.send_message("No items to remove!", ephemeral=True)
            return
        select = discord.ui.Select(placeholder="Select an item to remove", options=options)
        async def select_callback(interaction):
            item = select.values[0]
            del config['items'][item]
            save_config(config)
            await interaction.response.send_message(f"Removed item: {item}", ephemeral=True)
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.response.send_message("Select an item to remove:", view=view, ephemeral=True)

    @discord.ui.button(label="Check Stock Now", style=discord.ButtonStyle.blurple)
    async def check_stock_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        results = []
        for item_name, item_data in config['items'].items():
            for store, url in item_data['stores'].items():
                in_stock, image_url = await check_stock(store, url)
                status = "In Stock" if in_stock else "Out of Stock"
                results.append(f"**{item_name}** at **{store}**: {status} ([Link]({url}))")
        embed = discord.Embed(
            title="Manual Stock Check",
            description="\n".join(results) or "No items configured.",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

# Modal for adding a store
class AddStoreModal(discord.ui.Modal, title="Add Store"):
    store_name = discord.ui.TextInput(label="Store Name", placeholder="e.g., Pokemon Center UK")
    store_url = discord.ui.TextInput(label="Store Base URL", placeholder="e.g., https://uk.pokemoncenter.com")

    async def on_submit(self, interaction: discord.Interaction):
        config['stores'][self.store_name.value] = self.store_url.value
        save_config(config)
        await interaction.response.send_message(f"Added store: {self.store_name.value}", ephemeral=True)

# Modal for adding an item
class AddItemModal(discord.ui.Modal, title="Add Item"):
    item_name = discord.ui.TextInput(label="Item Name", placeholder="e.g., Prismatic Evolutions ETB")
    item_url = discord.ui.TextInput(label="Item URL", placeholder="e.g., https://uk.pokemoncenter.com/product/...")
    store_name = discord.ui.TextInput(label="Store Name", placeholder="e.g., Pokemon Center UK")

    async def on_submit(self, interaction: discord.Interaction):
        if self.store_name.value not in config['stores']:
            await interaction.response.send_message("Store not found! Add the store first.", ephemeral=True)
            return
        if self.item_name.value not in config['items']:
            config['items'][self.item_name.value] = {'stores': {}}
        config['items'][self.item_name.value]['stores'][self.store_name.value] = self.item_url.value
        save_config(config)
        await interaction.response.send_message(f"Added item: {self.item_name.value} for {self.store_name.value}", ephemeral=True)

# Health endpoint for UptimeRobot
async def health_check(request):
    return web.Response(text="Bot is running!")

# Run BOT and web server concurrently
async def main():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', 8000)))
    await site.start()
    await bot.start(DISCORD_TOKEN)

# Bot events and commands
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    stock_checker.start()

@bot.command()
async def setup(ctx):
    config['channel_id'] = str(ctx.channel.id)
    save_config(config)
    embed = discord.Embed(
        title="Pokémon Stock Bot",
        description="Use the buttons below to manage stores and items, or check stock manually. Stock alerts will be sent to #stock-alerts with @everyone pings.",
        color=discord.Color.blue()
    )
    embed.add_field(name="Status", value="Running - Checking every 60 seconds", inline=False)
    view = StockBotView()
    await ctx.send(embed=embed, view=view)

# Start the bot and web server
if __name__ == "__main__":
    asyncio.run(main())