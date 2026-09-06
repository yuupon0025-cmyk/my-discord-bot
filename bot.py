import json
import os
from datetime import datetime, timedelta
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

DATA_FILE = "queue_data.json"

queue_members = []
cooldowns = {}


# --- Renderポート開放用 ダミーWebサーバー ---
async def handle(request):
    return web.Response(text="Bot is running!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


# --- データの保存と読み込み処理 ---
def save_data():
    data = {
        "queue_members": queue_members,
        "cooldowns": {
            str(uid): dt.isoformat() for uid, dt in cooldowns.items()
        },
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_data():
    global queue_members, cooldowns
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                queue_members = data.get("queue_members", [])
                raw_cooldowns = data.get("cooldowns", {})
                cooldowns = {
                    int(uid): datetime.fromisoformat(dt_str)
                    for uid, dt_str in raw_cooldowns.items()
                }
        except Exception as e:
            print(f"Data load error: {e}")


class JoinButton(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="参加する", style=discord.ButtonStyle.primary, custom_id="join_btn"
    )
    async def join_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        user_id = interaction.user.id
        now = datetime.now()

        if user_id in cooldowns:
            unlock_time = cooldowns[user_id]
            if now < unlock_time:
                remaining_days = (unlock_time - now).days + 1
                await interaction.response.send_message(
                    f"過去に参加しているため、あと {remaining_days} 日間は参加できません。",
                    ephemeral=True,
                )
                return

        if user_id in queue_members:
            await interaction.response.send_message(
                "あなたはすでにリストに登録されています。（1人1回まで）",
                ephemeral=True,
            )
            return

        if len(queue_members) >= 15:
            await interaction.response.send_message(
                "すでに15人満員のため、参加できません。", ephemeral=True
            )
            return

        queue_members.append(user_id)
        cooldowns[user_id] = now + timedelta(days=15)
        save_data()

        embed, is_full = create_queue_embed()

        if is_full:
            button.disabled = True
            await interaction.message.edit(embed=embed, view=self)
            await interaction.response.send_message(
                f"{interaction.user.mention} さんが参加しました！これで15人満員となりました。",
                ephemeral=False,
            )
        else:
            await interaction.message.edit(embed=embed, view=self)
            await interaction.response.send_message(
                f"{interaction.user.mention} さんが参加しました！",
                ephemeral=True,
            )


def create_queue_embed():
    description_text = (
        "待機リストに登録されている状態は、あくまで「いずれテストを受けるための順番待ち」をしている状態であり、"
        "すぐにテストが実施されるわけではありません。あらかじめご了承ください。\n"
        "「キュー（待機列）」は、実際にテストを受ける準備が整った際に参加するものです。\n"
        "担当テスターが対応可能になると、通知が送られ、キューに参加するためのボタンが表示されます。\n"
        "このボタンは、評価テストのためにすぐにログインできる状態にあるプレイヤーを対象としています。\n"
        "対応可能なテスターがいない場合、キューは閉じられたままとなり、テスターが「稼働中（アクティブ）」のステータスにするまではボタンが表示されません。\n"
        "その時点で実際にテストを行っているテスターがいない場合、キューに関するメッセージは表示されません。\n"
        "テスターが「対応不可」のステータスに変更し、他に稼働中のテスターがいなくなった場合、キューは閉じられます。キューに参加していた場合でも、その順番は保存されません。\n"
        "テスターが対応可能になった時点で、通常通り改めてキューに参加することができます。"
    )

    embed = discord.Embed(
        title="待機リストについて",
        description=description_text,
        color=discord.Color.blue(),
    )

    list_lines = []
    for i in range(15):
        if i < len(queue_members):
            list_lines.append(f"{i+1}. <@{queue_members[i]}>")
        elif i == len(queue_members):
            list_lines.append(f"{i+1}. @参加可能")
        else:
            list_lines.append(f"{i+1}. @")

    embed.add_field(
        name="順番", value="\n".join(list_lines), inline=False
    )
    is_full = len(queue_members) >= 15
    return embed, is_full


@bot.event
async def on_ready():
    load_data()
    await start_web_server()  # ポート開放用のWebサーバーを起動
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)


@bot.tree.command(
    name="test", description="待機リストをリセットして新しく表示します"
)
async def test_command(interaction: discord.Interaction):
    global queue_members
    queue_members = []
    save_data()

    embed, is_full = create_queue_embed()
    view = JoinButton()

    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(
    name="reset", description="準備メンバー（キュー）のみをリセットします（管理者専用）"
)
@app_commands.checks.has_permissions(administrator=True)
async def reset_command(interaction: discord.Interaction):
    global queue_members
    queue_members = []
    save_data()
    await interaction.response.send_message(
        "準備メンバーのリストをリセットしました。（※15日間のクールダウン制限は保持されています）",
        ephemeral=True,
    )


@bot.tree.command(
    name="emergency_reset",
    description="【緊急用】準備メンバーおよび15日間の制限データをすべて初期化します（管理者専用）",
)
@app_commands.checks.has_permissions(administrator=True)
async def emergency_reset_command(interaction: discord.Interaction):
    global queue_members, cooldowns
    queue_members = []
    cooldowns = {}
    save_data()

    await interaction.response.send_message(
        "🚨 **緊急リセット完了**: 準備メンバーおよび15日間の再参加制限データをすべて初期化しました。全員が即時参加可能です。",
        ephemeral=True,
    )


@reset_command.error
@emergency_reset_command.error
async def admin_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "このコマンドを実行する権限（管理者権限）がありません。", ephemeral=True
        )


bot.run(os.environ.get("DISCORD_TOKEN"))