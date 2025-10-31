# -*- coding: utf-8 -*-
"""
AutoApproveBot (v4.4) - Final Corrected Code
Author: Sachin Sir 🔥
Core Functionality: Automatic Join Request Approval based on Force-Join checks with custom delay.
Owner Panel: Added "Set Delay" feature. Broadcast, Force-Join, Manage Owner unchanged.
Correction: All owners now have equal rights for text-based commands.
"""
import json
import os
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    ChatJoinRequest # Essential for handling join requests
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ChatJoinRequestHandler, # New handler for join requests
)
# <<<--- MODIFICATION START (OWNER FIX) --->>>
from telegram.ext.filters import BaseFilter
# <<<--- MODIFICATION END --->>>


# ================ CONFIG =================
BOT_TOKEN = "8311987428:AAGUYS4Oyhj0y7O74P0dz4IHfQSQ438x3kA" # <-- Replace with your actual bot token
OWNER_ID = 8070535163  # <-- Replace with your Telegram ID
DATA_FILE = "data.json"
# =========================================

# centralized welcome text (Modified for Auto Approve Bot)
WELCOME_TEXT = (
    "🤡 Hey you! \n"
    "I auto-approve faster than your crush ignores your texts. \n"
    "But I can’t work outside the group — add me there so I can show off!"
)

DEFAULT_DATA = {
    "subscribers": [],
    "owners": [OWNER_ID],
    "force": {
        "enabled": False,
        # channels: entries may be dict {"chat_id":..., "invite":..., "join_btn_text":...}
        "channels": [],
        "check_btn_text": "✅ Verify",
    },
    "approval_delay_minutes": 0, # New setting for approval delay
}


# ---------- Storage Helpers ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, indent=2)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # ensure required keys
    if "force" not in data:
        data["force"] = DEFAULT_DATA["force"]
    else:
        if "channels" not in data["force"]:
            data["force"]["channels"] = []
        if "check_btn_text" not in data["force"]:
            data["force"]["check_btn_text"] = DEFAULT_DATA["force"]["check_btn_text"]
    if "owners" not in data:
        data["owners"] = DEFAULT_DATA["owners"]
    if "subscribers" not in data:
        data["subscribers"] = DEFAULT_DATA["subscribers"]
    if "approval_delay_minutes" not in data:
        data["approval_delay_minutes"] = 0
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_owner(uid: int) -> bool:
    data = load_data()
    return uid in data.get("owners", [])

# <<<--- MODIFICATION START (OWNER FIX) --->>>
# This custom filter checks if a message is from any user in the owners list.
class IsOwnerFilter(BaseFilter):
    def filter(self, message):
        # Use the existing is_owner function to check permission
        return is_owner(message.from_user.id)

# Create an instance of the filter to be used in the handler
is_owner_filter = IsOwnerFilter()
# <<<--- MODIFICATION END --->>>


# ---------- Normalizers & Robust Helpers ----------
def _normalize_channel_entry(raw):
    """
    Accept either dict or string; returns dict with chat_id, invite, join_btn_text
    """
    if isinstance(raw, dict):
        return {
            "chat_id": raw.get("chat_id") or raw.get("chat") or None,
            "invite": raw.get("invite") or raw.get("url") or None,
            "join_btn_text": raw.get("join_btn_text") or raw.get("button") or None,
        }
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("http://") or text.startswith("https://"):
            return {"chat_id": None, "invite": text, "join_btn_text": None}
        else:
            return {"chat_id": text, "invite": None, "join_btn_text": None}
    return {"chat_id": None, "invite": None, "join_btn_text": None}


def _derive_query_chat_from_entry(ch):
    """
    From normalized channel dict, derive a queryable chat identifier (username with @) if possible.
    Returns string (e.g., "@channelname") or None if not derivable.
    """
    chat_id = ch.get("chat_id")
    invite = ch.get("invite")
    if chat_id:
        return chat_id
    if invite and "t.me/" in invite:
        parts = invite.rstrip("/").split("/")
        possible = parts[-1] if parts else ""
        if possible and not possible.lower().startswith(("joinchat", "+")):
            return possible if possible.startswith("@") else f"@{possible}"
    return None


async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    Returns (missing_list, check_failed_flag)
    - missing_list: list of normalized channel dicts where user is NOT member (or could not be verified)
    - check_failed_flag: True if bot couldn't attempt any membership check for any channel (rare)
    """
    data = load_data()
    force = data.get("force", {})
    raw_channels = force.get("channels", []) or []
    normalized = [_normalize_channel_entry(c) for c in raw_channels]

    if not normalized:
        return [], False

    any_check_attempted = False
    any_check_succeeded = False
    missing = []

    for ch in normalized:
        query_chat = _derive_query_chat_from_entry(ch)
        if query_chat:
            # try API check
            try:
                any_check_attempted = True
                member = await context.bot.get_chat_member(chat_id=query_chat, user_id=user_id)
                any_check_succeeded = True
                if member.status in ("left", "kicked"):
                    missing.append(ch)
                else:
                    pass
            except Exception:
                # Couldn't check (bot not in channel or invalid) -> treat as missing, but continue
                missing.append(ch)
                continue
        else:
            # No queryable username/invite; treat as missing
            missing.append(ch)

    check_failed = not any_check_attempted and any_check_succeeded is False
    return missing, check_failed


def build_join_keyboard_for_channels_list(ch_list, force_cfg):
    """
    Build a 2-column InlineKeyboardMarkup for only the channels in ch_list (normalized entries).
    Then append a single full-width Verify button at the end.
    """
    buttons = []
    for ch in ch_list:
        join_label = ch.get("join_btn_text") or "🔗 Join Channel"
        if ch.get("invite"):
            try:
                btn = InlineKeyboardButton(join_label, url=ch["invite"])
            except Exception:
                btn = InlineKeyboardButton(join_label, callback_data="force_no_invite")
        else:
            chat = ch.get("chat_id") or ""
            if chat and chat.startswith("@"):
                btn = InlineKeyboardButton(join_label, url=f"https://t.me/{chat.lstrip('@')}")
            else:
                btn = InlineKeyboardButton(join_label, callback_data="force_no_invite")
        buttons.append(btn)

    # arrange into 2-column rows
    rows = []
    i = 0
    while i < len(buttons):
        if i + 1 < len(buttons):
            rows.append([buttons[i], buttons[i + 1]])
            i += 2
        else:
            rows.append([buttons[i]])
            i += 1

    # verify button
    check_label = force_cfg.get("check_btn_text") or "✅ Verify"
    rows.append([InlineKeyboardButton(check_label, callback_data="check_join")])

    return InlineKeyboardMarkup(rows)


async def prompt_user_with_missing_channels(update: Update, context: ContextTypes.DEFAULT_TYPE, missing_norm_list, check_failed=False):
    """
    Show user only the missing channels' join buttons (2-column), then verify.
    If check_failed True and missing list empty -> show an informative message.
    """
    if not missing_norm_list and not check_failed:
        # Should not happen in this path, but as a safeguard:
        return 

    # Determine the recipient chat ID
    if update.callback_query:
        recipient_id = update.callback_query.message.chat_id
    elif isinstance(update, Update) and hasattr(update, 'chat_join_request') and update.chat_join_request:
        recipient_id = update.chat_join_request.from_user.id # Send to the requesting user in private chat
    else:
        recipient_id = update.message.chat_id

    if missing_norm_list:
        # smart messaging: differentiate between 0 joined vs some joined
        total = len(load_data().get("force", {}).get("channels", []))
        missing_count = len(missing_norm_list)
        joined_count = max(0, total - missing_count)
        
        if joined_count == 0:
            text = (
                "🔒 *Access Restricted*\n\n"
                "You need to join the required channels before being approved.\n\n"
                "Tap each **Join** button below, join those channels, and then press **Verify** to continue."
            )
        else:
            text = (
                "🔒 *Access Restricted*\n\n"
                "You’ve joined some channels, but a few are still left.\n\n"
                "Tap the **Join** buttons below for the remaining channels, then press **Verify** once done."
            )

        kb = build_join_keyboard_for_channels_list(missing_norm_list, load_data().get("force", {}))
    
    else: # check_failed is True and missing_norm_list is empty
        text = "⚠️ I couldn't verify memberships (bot may not have access). Owner, please check bot permissions."
        kb = None

    # Send the message and handle the original join request if applicable
    try:
        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
        
        elif isinstance(update, Update) and hasattr(update, 'chat_join_request') and update.chat_join_request:
            # 1. Send verification message to user's private chat
            await context.bot.send_message(recipient_id, text, parse_mode="Markdown", reply_markup=kb)
            
            # 2. Decline the original request. The user will re-request after verification.
            # This is crucial because an *approved* request cannot be undone.
            try:
                await context.bot.decline_chat_join_request(
                    chat_id=update.chat_join_request.chat.id,
                    user_id=update.chat_join_request.from_user.id
                )
            except Exception as e:
                print(f"Failed to decline join request for {recipient_id}: {e}")

        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        print(f"Failed to send prompt message to user {recipient_id}: {e}")


# ---------- Keyboards ----------
def owner_panel_kb():
    kb = [
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast"),
            InlineKeyboardButton("🔒 Force Join Setting", callback_data="owner_force"),
        ],
        [
            InlineKeyboardButton("🧑‍💼 Manage Owner", callback_data="owner_manage"),
            InlineKeyboardButton("🕒 Set Delay", callback_data="owner_set_delay") # New Button
        ],
        [InlineKeyboardButton("⬅️ Close", callback_data="owner_close")],
    ]
    return InlineKeyboardMarkup(kb)


def force_setting_kb(force: dict):
    kb = [
        [InlineKeyboardButton("🔁 Toggle Force-Join", callback_data="force_toggle"),
         InlineKeyboardButton("➕ Add Channel", callback_data="force_add")],
        [InlineKeyboardButton("🗑️ Remove Channel", callback_data="force_remove"),
         InlineKeyboardButton("📜 List Channel", callback_data="force_list")],
        [InlineKeyboardButton("⬅️ Back", callback_data="force_back")],
    ]
    return InlineKeyboardMarkup(kb)


def cancel_btn():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)


# ---------- Commands ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    # Owner bypass (Owners don't need to pass force checks)
    if not is_owner(user.id):
        force = data.get("force", {})
        if force.get("enabled", False):
            if force.get("channels"):
                missing, check_failed = await get_missing_channels(context, user.id)
                if not missing:
                    # user is member of all -> ensure in subscribers
                    subs = data.setdefault("subscribers", [])
                    if user.id not in subs:
                        subs.append(user.id)
                        save_data(data)
                else:
                    # If force-join enabled and checks fail, prompt the user.
                    subs = data.setdefault("subscribers", [])
                    if user.id in subs:
                        subs.remove(user.id)
                        save_data(data)
                    await prompt_user_with_missing_channels(update, context, missing, check_failed)
                    return
            else:
                # Force-Join enabled but no channels configured -> warn
                await update.message.reply_text("⚠️ Force-Join is enabled but no channels are configured. Owner, please configure channels via /owner.")
                return

    # normal welcome for verified/owner users
    subs = data.setdefault("subscribers", [])
    if user.id not in subs:
        subs.append(user.id)
        save_data(data)

    # Create the "Add to Group" button
    bot_username = (await context.bot.get_me()).username
    add_to_group_button = InlineKeyboardButton(
        "➕ Add Me To Your Group ➕",
        url=f"https://t.me/{bot_username}?startgroup=true"
    )
    keyboard = InlineKeyboardMarkup([[add_to_group_button]])

    await update.message.reply_text(
        WELCOME_TEXT, 
        parse_mode="Markdown",
        reply_markup=keyboard # Add the button here
    )


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only owners can access this panel.")
        return
    await update.message.reply_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())


# ---------- Callback Handler ----------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    payload = query.data
    data = load_data()

    # Owner panel close
    if payload == "owner_close":
        await query.message.edit_text("✅ Owner panel closed.")
        return

    if payload == "owner_set_delay":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can set the approval delay.")
            return
        current_delay = data.get("approval_delay_minutes", 0)
        context.user_data["flow"] = "set_delay_time"
        await query.message.reply_text(
            f"🕒 *Set Approval Delay*\n\nCurrent delay is `{current_delay}` minutes.\n\n"
            "Send the new delay time in minutes (e.g., `5` for 5 minutes). Send `0` for immediate approval.",
            parse_mode="Markdown",
            reply_markup=cancel_btn()
        )
        return

    # --- Owner Panel Logic ---
    if payload == "owner_broadcast":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can broadcast.")
            return
        context.user_data["flow"] = "broadcast_text"
        await query.message.reply_text("📢 Send the text to broadcast:", reply_markup=cancel_btn())
        return

    if payload == "owner_manage":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can manage owners.")
            return
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ Add Owner", callback_data="mgr_add"), InlineKeyboardButton("📜 List Owners", callback_data="mgr_list")],
                [InlineKeyboardButton("🗑️ Remove Owner", callback_data="mgr_remove"), InlineKeyboardButton("⬅️ Back", callback_data="mgr_back")],
            ]
        )
        await query.message.edit_text("🧑‍💼 *Manage Owner*", parse_mode="Markdown", reply_markup=kb)
        return

    if payload == "mgr_add":
        context.user_data["flow"] = "mgr_add"
        await query.message.reply_text("➕ Send numeric user ID to add as owner:", reply_markup=cancel_btn())
        return

    if payload == "mgr_list":
        owners = data.get("owners", [])
        msg = "🧑‍💼 *Owners:*\n" + "\n".join([f"{i+1}. `{o}`" for i, o in enumerate(owners)])
        await query.message.reply_text(msg, parse_mode="Markdown")
        return

    if payload == "mgr_remove":
        owners = data.get("owners", [])
        if len(owners) <= 1:
            await query.message.reply_text("❌ At least one owner must remain.")
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"Remove {o}", callback_data=f"mgr_rem_{i}")] for i, o in enumerate(owners)])
        await query.message.reply_text("Select an owner to remove:", reply_markup=kb)
        return

    if payload.startswith("mgr_rem_"):
        idx = int(payload.split("_")[-1])
        try:
            removed = data["owners"].pop(idx)
            save_data(data)
            await query.message.reply_text(f"✅ Removed owner `{removed}`", parse_mode="Markdown")
        except Exception:
            await query.message.reply_text("❌ Invalid selection.")
        return

    if payload == "mgr_back":
        await query.message.edit_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())
        return

    # --- Force Join Setting Logic ---
    if payload == "owner_force":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can change force-join settings.")
            return
        force = data.get("force", {})
        status_text = "Enabled ✅" if force.get("enabled", False) else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status_text}`\n\nChoose an action:"
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        return

    if payload == "force_toggle":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can toggle force-join.")
            return
        data = load_data()
        force = data.setdefault("force", {})
        new_state = not force.get("enabled", False)
        force["enabled"] = new_state
        save_data(data)
        status_text = "Enabled ✅" if new_state else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status_text}`\n\nChoose an action:"
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        if new_state and not force.get("channels"):
            await query.message.reply_text("⚠️ Force-Join enabled but no channels configured. Add channels using Add Channel.", parse_mode="Markdown")
        return

    if payload == "force_add":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can add channels.")
            return
        context.user_data["flow"] = "force_add_step1"
        await query.message.reply_text(
            "➕ *Add Channel*\n\nSend channel identifier or invite link.\nExamples:\n - `@MyChannel`\n - `-1001234567890`\n - `https://t.me/joinchat/XXXX`",
            parse_mode="Markdown",
            reply_markup=cancel_btn(),
        )
        return

    if payload == "force_remove":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can remove channels.")
            return
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            await query.message.reply_text("ℹ️ No channels configured.")
            return
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"Remove: {ch.get('chat_id') or ch.get('invite') or str(i)}", callback_data=f"force_rem_{i}")] for i, ch in enumerate(channels)]
        )
        await query.message.reply_text("Select channel to remove:", reply_markup=kb)
        return

    if payload.startswith("force_rem_"):
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can remove channels.")
            return
        try:
            idx = int(payload.split("_")[-1])
            channels = data.get("force", {}).get("channels", [])
            removed = channels.pop(idx)
            data["force"]["channels"] = channels
            save_data(data)
            await query.message.reply_text(f"✅ Removed channel `{removed.get('chat_id') or removed.get('invite')}`", parse_mode="Markdown")
        except Exception:
            await query.message.reply_text("❌ Invalid selection.")
        return

    if payload == "force_list":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can view channels.")
            return
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            await query.message.reply_text("ℹ️ No channels configured.")
            return
        lines = ["📜 *Configured Channels:*"]
        for i, ch in enumerate(channels, start=1):
            lines.append(f"{i}. `chat_id`: `{ch.get('chat_id') or '—'}`\n   `invite`: `{ch.get('invite') or '—'}`\n   `button`: `{ch.get('join_btn_text') or '🔗 Join Channel'}`")
        await query.message.reply_text("\n\n".join(lines), parse_mode="Markdown")
        return

    if payload == "force_back":
        await query.message.edit_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())
        return

    if payload == "force_no_invite":
        await query.message.reply_text("⚠️ No invite URL configured for this channel. Contact the owner.")
        return

    # --- Verification Logic ---
    if payload == "check_join":
        uid = query.from_user.id
        data = load_data()
        
        if is_owner(uid) or not data.get("force", {}).get("enabled", False):
            await query.message.reply_text("✅ Verification passed. Access granted.")
            return

        missing, check_failed = await get_missing_channels(context, uid)
        
        if not missing:
            # Step 1: User is verified. Add to subscribers.
            subs = data.setdefault("subscribers", [])
            if uid not in subs:
                subs.append(uid)
                save_data(data)

            # Step 2: Inform user and send welcome message
            await query.message.reply_text("✅ Verification complete!")
            
            # Create the "Add to Group" button
            bot_username = (await context.bot.get_me()).username
            add_to_group_button = InlineKeyboardButton(
                "➕ Add Me To Your Group ➕",
                url=f"https://t.me/{bot_username}?startgroup=true"
            )
            keyboard = InlineKeyboardMarkup([[add_to_group_button]])
            
            await query.message.reply_text(
                WELCOME_TEXT, 
                parse_mode="Markdown",
                reply_markup=keyboard # Add the button here
            )
        else:
            # Step 3: Verification failed. Remove from subscribers and re-prompt.
            subs = data.setdefault("subscribers", [])
            if uid in subs:
                subs.remove(uid)
                save_data(data)
            
            # Delete the previous verification message before sending a new one
            try:
                await query.message.delete()
            except Exception:
                pass

            await prompt_user_with_missing_channels(update, context, missing, check_failed=check_failed)
        return

    return


# ---------- Owner Text Handler (flows) ----------
async def owner_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # This handler now works for any user confirmed by is_owner(), not just the hardcoded one.
    if not is_owner(uid):
        return
    data = load_data()
    text = update.message.text.strip()
    flow = context.user_data.get("flow")

    # Cancel
    if text == "❌ Cancel":
        context.user_data.clear()
        await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    # Set approval delay flow
    if flow == "set_delay_time":
        try:
            delay_minutes = int(text)
            if delay_minutes < 0:
                await update.message.reply_text("❌ Please send a non-negative number (0 or more).")
                return
        except ValueError:
            await update.message.reply_text("❌ Invalid input. Please send a numeric value for minutes.")
            return

        data["approval_delay_minutes"] = delay_minutes
        save_data(data)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Approval delay set to `{delay_minutes}` minutes.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return
        
    # Broadcast flow
    if flow == "broadcast_text":
        subs = data.get("subscribers", [])
        sent = 0
        failed = 0
        for u in subs:
            try:
                await context.bot.send_message(u, text)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(f"✅ Broadcast done. Sent: {sent}, Failed: {failed}", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return

    # Add owner flow
    if flow == "mgr_add":
        try:
            new_owner = int(text)
        except Exception:
            await update.message.reply_text("❌ Please send numeric ID.")
            return
        owners = data.setdefault("owners", [])
        if new_owner in owners:
            await update.message.reply_text("Already an owner.")
            context.user_data.clear()
            return
        owners.append(new_owner)
        save_data(data)
        context.user_data.clear()
        await update.message.reply_text(f"✅ Added owner `{new_owner}`", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        return

    # Force add - step1: received chat_id or invite
    if flow == "force_add_step1":
        entry = {"chat_id": None, "invite": None, "join_btn_text": None}
        if text.startswith("http://") or text.startswith("https://"):
            entry["invite"] = text
        else:
            entry["chat_id"] = text
        context.user_data["force_add_entry"] = entry
        context.user_data["flow"] = "force_add_step2"
        await update.message.reply_text(
            f"✅ Channel detected: `{entry.get('chat_id') or entry.get('invite')}`\n\nNow send the button text to show to users (e.g. `🔗 Join Channel` or `🚀 Join Updates`).",
            parse_mode="Markdown",
            reply_markup=cancel_btn(),
        )
        return

    # Force add - step2: received button text
    if flow == "force_add_step2":
        entry = context.user_data.get("force_add_entry")
        if not entry:
            context.user_data.clear()
            await update.message.reply_text("❌ Unexpected error. Try again.", reply_markup=ReplyKeyboardRemove())
            return
        btn = text
        if len(btn) > 40:
            await update.message.reply_text("❌ Button text too long (max 40 chars). Send shorter text.")
            return
        entry["join_btn_text"] = btn
        channels = data.setdefault("force", {}).setdefault("channels", [])
        channels.append(entry)
        data["force"]["channels"] = channels
        save_data(data)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Channel added!\n`{entry.get('chat_id') or entry.get('invite')}`\nButton: `{btn}`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # default fallback
    context.user_data.clear()


# ---------- New Functions for Delayed Approval ----------
async def _approve_user_job(context: ContextTypes.DEFAULT_TYPE):
    """Job callback to approve a user after a delay."""
    job = context.job
    chat_id = job.data["chat_id"]
    user_id = job.data["user_id"]
    try:
        await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        print(f"Delayed approval successful for user {user_id} in chat {chat_id}.")
        # Optional: Send a success message after approval
        try:
            await context.bot.send_message(user_id, "✅ You have been automatically approved to the channel!", parse_mode="Markdown")
        except Exception:
            pass # Fail silently
    except Exception as e:
        print(f"Failed to execute delayed approval for user {user_id} in chat {chat_id}: {e}")


async def _process_approval(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    """Handles the approval logic, either immediate or delayed."""
    data = load_data()
    delay_minutes = data.get("approval_delay_minutes", 0)

    if delay_minutes > 0:
        delay_seconds = delay_minutes * 60
        context.job_queue.run_once(
            _approve_user_job,
            when=delay_seconds,
            data={"chat_id": chat_id, "user_id": user_id},
            name=f"approve-{chat_id}-{user_id}"
        )
        print(f"Scheduled approval for user {user_id} in {chat_id} in {delay_minutes} minutes.")
    else: # Immediate approval
        try:
            await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
            print(f"User {user_id} automatically approved to {chat_id}.")
            # Optional: Send a welcome message
            try:
                await context.bot.send_message(user_id, "✅ You have been automatically approved to the channel!", parse_mode="Markdown")
            except Exception:
                pass
        except Exception as e:
            print(f"Failed to approve user {user_id} to {chat_id}: {e}")


# ---------- New Chat Join Request Handler (Core Auto-Approve Logic) ----------
async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles a new join request to a channel.
    Checks force-join requirements (if enabled) and auto-approves if conditions are met,
    or prompts the user for verification.
    """
    chat_join_request: ChatJoinRequest = update.chat_join_request
    user_id = chat_join_request.from_user.id
    chat_id = chat_join_request.chat.id
    data = load_data()

    # 1. Owner bypass: owners are always approved (respecting delay)
    if is_owner(user_id):
        await _process_approval(context, chat_id, user_id)
        return

    force = data.get("force", {})

    # 2. Check Force-Join status
    if force.get("enabled", False) and force.get("channels"):
        
        # Check if the user meets the force-join requirements
        missing, check_failed = await get_missing_channels(context, user_id)
        
        if not missing:
            # User is a member of all required channels -> Approve (respecting delay)
            await _process_approval(context, chat_id, user_id)
            
        else:
            # User is missing channels or check failed -> Prompt for verification
            # Declining the request is handled inside prompt_user_with_missing_channels
            await prompt_user_with_missing_channels(update, context, missing, check_failed)
            print(f"User {user_id} denied auto-approval and prompted for verification.")
            
    else:
        # Force-join disabled or no channels configured -> Auto-Approve (respecting delay)
        await _process_approval(context, chat_id, user_id)


# ---------- Run ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands & callback handler
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Crucial: Handler for automatic approval logic
    app.add_handler(ChatJoinRequestHandler(handle_join_request))
    
    # <<<--- MODIFICATION START (OWNER FIX) --->>>
    # This handler now correctly works for ALL owners in the data file, not just the one in OWNER_ID
    app.add_handler(MessageHandler(is_owner_filter & filters.TEXT & ~filters.COMMAND, owner_text_handler))
    # <<<--- MODIFICATION END --->>>

    print("🤖 AutoApproveBot v4.4 (Corrected) running...")
    app.run_polling()


if __name__ == "__main__":
    main()
