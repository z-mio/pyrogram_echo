from pyrogram import Client
from pyrogram.errors import MessageTooLong
from pyrogram.raw.base import Update
from pyrogram.raw.types import (
    PeerChannel,
    PeerChat,
    UpdateBotMessageReaction,
    UpdateChannelMessageViews,
)
from pyrogram.types import ChatMemberUpdated, Message, Object, ReplyParameters


@Client.on_message()
@Client.on_chat_member_updated()
async def echo(cli: Client, msg: Message | ChatMemberUpdated, prefix_text: str = "") -> None:
    """处理消息和成员更新事件，递归显示消息结构"""

    if isinstance(msg, Message):
        message = await cli.get_messages(msg.chat.id, msg.id) if getattr(msg, "id", None) else msg
    else:
        message = msg

    chat_id = message.chat.id
    message_id = getattr(message, "id", None)

    if getattr(message, "reply_to_message", None):
        await echo(cli, message.reply_to_message, "reply_to_message.")
        message.reply_to_message = None

    try:
        await _send_formatted_message(cli, chat_id, message_id, prefix_text, "message", message)
    except MessageTooLong:
        await _handle_long_message(cli, chat_id, message_id, prefix_text, message)


@Client.on_raw_update(group=1)
async def raw_update(cli: Client, update: Update, users: dict, chats: dict) -> None:
    """处理原始更新事件"""
    if isinstance(update, UpdateBotMessageReaction):
        await handle_reaction(cli, update)
    elif isinstance(update, UpdateChannelMessageViews):
        channel_id = _convert_to_channel_id(update.channel_id)
        await cli.send_message(channel_id, format_as_blockquote(update))


async def handle_reaction(cli: Client, update: UpdateBotMessageReaction) -> None:
    """处理消息反应事件"""
    chat_id = _extract_chat_id_from_peer(update.peer)
    if not chat_id:
        return

    await cli.send_message(
        chat_id=chat_id,
        text=format_as_blockquote(update),
        reply_parameters=ReplyParameters(message_id=update.msg_id),
    )


async def _send_formatted_message(
    cli: Client, chat_id: int, message_id: int | None, prefix: str, name: str, data: object
) -> None:
    """发送格式化后的消息"""
    await cli.send_message(
        chat_id=chat_id,
        text=f"{format_as_blockquote(data)}**{prefix}{name}**",
        reply_to_message_id=message_id,
    )


async def _send_simple_message(cli: Client, chat_id: int, prefix: str, name: str) -> None:
    """发送简单的提示消息（用于数据过长的情况）"""
    await cli.send_message(chat_id=chat_id, text="> 数据过长\n**{}**".format(f"{prefix}{name}"))


async def _handle_long_message(
    cli: Client, chat_id: int, message_id: int | None, prefix: str, message: Message | ChatMemberUpdated
) -> None:
    """处理消息过长的情况，逐个发送属性"""
    attrs_to_clear = []

    for attr_name in dir(message):
        # 跳过私有属性
        if attr_name.startswith("_"):
            continue

        attr_value = getattr(message, attr_name)

        # 跳过方法或空值
        if callable(attr_value) or not attr_value:
            continue

        # 只处理 Object 类型或包含 entities 的属性
        if not (isinstance(attr_value, Object) or "entities" in attr_name):
            continue

        # 发送该嵌套属性值
        try:
            await _send_formatted_message(cli, chat_id, None, prefix, attr_name, attr_value)
        except MessageTooLong:
            await _send_simple_message(cli, chat_id, prefix, attr_name)

        # 记录已发送并需要清理的属性（保留 chat 作为基本定位）
        if attr_name != "chat":
            attrs_to_clear.append(attr_name)

    # 批量将已发送的属性和 chat 置空（让 Pyrogram 序列化时忽略它们），精简最终输出
    for attr_name in attrs_to_clear + ["chat"]:
        setattr(message, attr_name, None)

    await _send_formatted_message(cli, chat_id, message_id, prefix, "message", message)


def _extract_chat_id_from_peer(peer) -> int | None:
    """从 peer 对象中提取完整的聊天ID"""
    if isinstance(peer, PeerChannel):
        return _convert_to_channel_id(peer.channel_id)
    elif isinstance(peer, PeerChat):  # 兼容普通群组
        return int(f"-{peer.chat_id}")
    elif hasattr(peer, "user_id"):  # 兼容 PeerUser 等包含 user_id 的类型
        return peer.user_id
    return None


def _convert_to_channel_id(channel_id: int) -> int:
    """将频道ID转换为 Supergroup/Channel 完整的聊天ID"""
    return int(f"-100{channel_id}")


def format_as_blockquote(content: object) -> str:
    """将内容格式化为可折叠的引用块"""
    return f"<blockquote expandable>\n{content}</blockquote>"
