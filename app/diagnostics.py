"""Safe failure locations without exception messages, source text or frame locals."""
import logging
from pathlib import Path


def failure(logger_name, operation, error):
    # Do not use exc_info: provider exception strings/chains may contain credentials.
    frames = []
    tb = error.__traceback__
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(f'{Path(code.co_filename).name}:{tb.tb_lineno}:{code.co_name}')
        tb = tb.tb_next
    logging.getLogger(logger_name).error('%s failed (%s); frames=%s',
        operation, type(error).__name__, ' > '.join(frames) or 'unavailable')
