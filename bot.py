from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands

# インテントの設定
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# データの保持（メモリ上）
queue_members = []  # 現在のリストに入っているユーザーIDのリスト
cooldowns = {}  # ユーザーID: 制限解除日時 (15日間参加不可の管理用)


# 参加ボタンのコンポーネント定義
class JoinButton(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)  # ボタンを永続化（無期限）

    @discord.ui.button(
        label="参加する", style=discord.ButtonStyle.primary, custom_id="join_btn"
    )
    async def join_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        user_id = interaction.user.id
        now = datetime.now()

        # 1. 15日間のクールダウンチェック
        if user_id in cooldowns:
            unlock_time = cooldowns[user_id]
            if now < unlock_time:
                remaining_days = (unlock_time - now).days + 1
                await interaction.response.send_message(
                    f"過去に参加しているため、あと {remaining_days} 日間は参加できません。",
                    ephemeral=True,
                )
                return

        # 2. すでに現在のリストに入っているかチェック
        if user_id in queue_members:
            await interaction.response.send_message(
                "あなたはすでにリストに登録されています。（1人1回まで）",
                ephemeral=True,
            )
            return

        # 3. 15人満員チェック
        if len(queue_members) >= 15:
            await interaction.response.send_message(
                "すでに15人満員のため、参加できません。", ephemeral=True
            )
            return

        # 条件をクリアした場合の処理
        queue_members.append(user_id)
        # 15日間の再参加不可タイマーを設定
        cooldowns[user_id] = now + timedelta(days=15)

        # 埋め込みメッセージとリストの再構築
        embed, is_full = create_queue_embed()

        # 15人達したらボタンを無効化する
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


# 埋め込みメッセージを作成する共通関数
def create_queue_embed():
    description_text = (
        "待機リストに登録されている状態は、あくまで「いずれテストを受けるための順番待ち」をしている状態であり、"
        "すぐにテストが実施されるわけではありません。あらかじめご了承ください。\n"
        "「キュー（待機列）」は、実際にテストを受ける準備が整った際に参加するものです。\n"
        "担当テスターが対応可能になると、で通知が送られ、キューに参加するためのボタンが表示されます。\n"
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

    # 15人分のリストを作成
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
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)


# /test コマンド：実行時に準備メンバーをすべてリセットして新規作成
@bot.tree.command(
    name="test", description="待機リストをリセットして新しく表示します"
)
async def test_command(interaction: discord.Interaction):
    global queue_members
    queue_members = []  # 準備メンバー（現在のキュー）を初期化

    embed, is_full = create_queue_embed()
    view = JoinButton()

    await interaction.response.send_message(embed=embed, view=view)


# /reset コマンド：準備メンバーのみリセット（15日間の制限は残す）
@bot.tree.command(
    name="reset", description="準備メンバー（キュー）のみをリセットします（管理者専用）"
)
@app_commands.checks.has_permissions(administrator=True)
async def reset_command(interaction: discord.Interaction):
    global queue_members
    queue_members = []
    await interaction.response.send_message(
        "準備メンバーのリストをリセットしました。（※15日間のクールダウン制限は保持されています）",
        ephemeral=True,
    )


# /emergency_reset コマンド：15日間制限も含めて完全初期化
@bot.tree.command(
    name="emergency_reset",
    description="【緊急用】準備メンバーおよび15日間の制限データをすべて初期化します（管理者専用）",
)
@app_commands.checks.has_permissions(administrator=True)
async def emergency_reset_command(interaction: discord.Interaction):
    global queue_members, cooldowns
    queue_members = []  # キューをクリア
    cooldowns = {}  # 15日間制限のデータを完全初期化

    await interaction.response.send_message(
        "🚨 **緊急リセット完了**: 準備メンバーおよび15日間の再参加制限データをすべて初期化しました。全員が即時参加可能です。",
        ephemeral=True,
    )


# エラーハンドリング（権限がないユーザーが管理者コマンドを叩いた場合）
@reset_command.error
@emergency_reset_command.error
async def admin_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "このコマンドを実行する権限（管理者権限）がありません。", ephemeral=True
        )


# Botを実行（ご自身のトークンを入力してください）
import os

bot.run(os.environ.get("DISCORD_TOKEN"))