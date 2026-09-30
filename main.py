"""Python 3.11 entrypoint for BotHost. Credentials come only from environment."""
import logging
import signal
import time
from bot import Bot
from protocol import VERSION, BUILD
from transport import ApiError, Config, Panel, Telegram
from workshop import websocket_backend, WorkshopError

running = True


def stop(*_):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        _, backend = websocket_backend()
        logging.info('GeniusMobilus %s %s; Workshop: %s', VERSION, BUILD, backend)
    except WorkshopError as error:
        logging.warning('Workshop disabled: %s', error)
    config = Config.environment()
    tg = Telegram(config.token)
    bot = Bot(config, tg, Panel(config))
    # This is a polling bot. Discard queued commands at every cold start:
    # resurrecting a confirmation after a host restart is never intended.
    tg.call('deleteWebhook', drop_pending_updates=True)
    offset = 0
    logging.info('GeniusMobilus %s %s started; configured admins: %d', VERSION, BUILD, len(config.admins))
    while running:
        try:
            updates = tg.call('getUpdates', offset=offset, timeout=25,
                             allowed_updates=['message', 'callback_query'])
            for update in updates:
                offset = max(offset, update['update_id'] + 1)
                try:
                    bot.update(update)
                except Exception as error:
                    # Do not log exception text: urllib errors can contain bot URLs.
                    logging.error('Update failed (%s); no automatic action retry', type(error).__name__)
        except ApiError as error:
            logging.warning('%s', error)
            time.sleep(5)


if __name__ == '__main__':
    try:
        main()
    except ApiError as error:
        logging.error('%s', error)
        raise SystemExit(1) from None
