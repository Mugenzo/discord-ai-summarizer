# How to Invite Your Bot to Discord Server

## Step-by-Step Instructions

1. **Go to Discord Developer Portal**
   - Visit: https://discord.com/developers/applications
   - Select your application

2. **Generate Invite URL**
   - Click on **"OAuth2"** in the left sidebar
   - Click on **"URL Generator"**

3. **Select Scopes** (check these boxes):
   - ✅ `bot`
   - ✅ `applications.commands` (optional, for slash commands)

4. **Select Bot Permissions** (scroll down and check):
   - ✅ **Read Messages** (under Text Permissions)
   - ✅ **Send Messages** (under Text Permissions)
   - ✅ **Embed Links** (under Text Permissions)
   - ✅ **Connect** (under Voice Permissions)
   - ✅ **Speak** (under Voice Permissions)
   - ✅ **Use Voice Activity** (under Voice Permissions)

5. **Copy the Generated URL**
   - Scroll to the bottom
   - Copy the URL that looks like:
     ```
     https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=PERMISSIONS&scope=bot%20applications.commands
     ```

6. **Open the URL in Your Browser**
   - Paste the URL in your browser
   - Select the server you want to add the bot to
   - Click "Authorize"
   - Complete any CAPTCHA if prompted

7. **Verify Bot is in Server**
   - Go to your Discord server
   - Check the member list on the right
   - The bot should appear (may show as offline until you start it)

## Troubleshooting

**Bot not appearing?**
- Make sure you completed the authorization
- Check that you have "Manage Server" permission in that server
- The bot will show as offline until you run `python bot.py`

**Bot shows as offline?**
- Start the bot: `source venv/bin/activate && python bot.py`
- The bot should show as online once it connects

**Permission errors?**
- Make sure you selected all required permissions in the URL generator
- The bot needs "Connect" and "Speak" permissions for voice channels

