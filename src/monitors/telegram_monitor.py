"""
Telegram channel/chat monitor using Telethon.
"""

import asyncio
from typing import Callable, Optional, Union, List, Set
from datetime import datetime

from telethon import TelegramClient, events
from telethon.tl.types import Channel, Chat, User
from telethon.tl.functions.updates import GetStateRequest
from loguru import logger


class TelegramMonitor:
    def __init__(
        self,
        api_id,         # type: int
        api_hash,       # type: str
        session_name="token_detector",  # type: str
        phone=None,     # type: Optional[str]
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.phone = phone

        self.client = None  # type: Optional[TelegramClient]
        self.sources = set()  # type: Set[Union[str, int]]
        self._message_handler = None  # type: Optional[Callable]
        self._running = False

    async def start(self):
        # type: () -> None
        self.client = TelegramClient(
            self.session_name,
            self.api_id,
            self.api_hash,
        )

        await self.client.start(phone=self.phone)
        # Force sync update state so events are received immediately
        await self.client(GetStateRequest())
        logger.info("Telegram client started successfully")

        me = await self.client.get_me()
        logger.info("Logged in as: {} (@{})".format(me.first_name, me.username))

    async def stop(self):
        # type: () -> None
        self._running = False
        if self.client:
            await self.client.disconnect()
            logger.info("Telegram client disconnected")

    def add_source(self, source):
        # type: (Union[str, int]) -> None
        self.sources.add(source)
        logger.info("Added source: {}".format(source))

    def add_sources(self, sources):
        # type: (List[Union[str, int]]) -> None
        for source in sources:
            self.add_source(source)

    def on_message(self, handler):
        # type: (Callable) -> Callable
        self._message_handler = handler
        return handler

    async def _resolve_source(self, source):
        # type: (Union[str, int]) -> Optional[any]
        try:
            entity = await self.client.get_entity(source)
            # Return the entity itself (not just ID) for reliable event matching
            return entity
        except Exception as e:
            logger.error("Failed to resolve source {}: {}".format(source, e))
            return None

    async def _get_source_name(self, chat):
        # type: (any) -> str
        if hasattr(chat, 'title'):
            return chat.title
        elif hasattr(chat, 'username') and chat.username:
            return "@{}".format(chat.username)
        elif hasattr(chat, 'first_name'):
            return chat.first_name
        return str(chat.id)

    async def run(self):
        # type: () -> None
        if not self.client:
            await self.start()

        if not self.sources:
            logger.warning("No sources configured!")
            return

        if not self._message_handler:
            logger.warning("No message handler registered!")
            return

        resolved_sources = []
        for source in self.sources:
            entity = await self._resolve_source(source)
            if entity:
                resolved_sources.append(entity)
                entity_id = getattr(entity, 'id', '?')
                logger.info("Monitoring: {} (ID: {})".format(source, entity_id))
            else:
                logger.warning("Could not resolve source: {}".format(source))

        if not resolved_sources:
            logger.error("No valid sources to monitor!")
            return

        @self.client.on(events.NewMessage(chats=resolved_sources))
        async def handler(event):
            try:
                message = event.message
                text = message.text or message.caption or ""

                if not text:
                    return

                chat = await event.get_chat()
                source_name = await self._get_source_name(chat)
                timestamp = message.date

                logger.debug("New message from {}: {}...".format(source_name, text[:100]))

                await self._message_handler(text, source_name, timestamp)

            except Exception as e:
                logger.error("Error handling message: {}".format(e))

        self._running = True
        logger.info("Started monitoring {} sources".format(len(resolved_sources)))

        while self._running:
            await asyncio.sleep(1)

    async def send_message(self, target, text):
        # type: (Union[str, int], str) -> bool
        try:
            await self.client.send_message(target, text)
            logger.debug("Sent message to {}: {}...".format(target, text[:50]))
            return True
        except Exception as e:
            logger.error("Failed to send message to {}: {}".format(target, e))
            return False
