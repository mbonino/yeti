import json
import logging
import queue
from logging import Formatter
from logging.handlers import QueueHandler, QueueListener

# Inspired by 
# * https://www.sheshbabu.com/posts/fastapi-structured-json-logging/
# * https://rob-blackbourn.medium.com/how-to-use-python-logging-queuehandler-with-dictconfig-1e8b1284e27a

class JsonFormatter(Formatter):
    def __init__(self):
        super(JsonFormatter, self).__init__()

    def format(self, record):
        json_record = {}
        json_record["message"] = record.getMessage()
        if "username" in record.__dict__:
            json_record["username"] = record.__dict__["username"]
        if "path" in record.__dict__:
            json_record["path"] = record.__dict__["path"]
        if "method" in record.__dict__:
            json_record["method"] = record.__dict__["method"]
        if "body" in record.__dict__:
            json_record["body"] = json.loads(record.__dict__["body"].decode("utf-8"))
        if record.levelno == logging.ERROR and record.exc_info:
            json_record["err"] = self.formatException(record.exc_info)
        return json.dumps(json_record)


log_queue = queue.Queue(-1)
queue_handler = QueueHandler(log_queue)

logger = logging.getLogger()
logger.addHandler(queue_handler)

formatter = JsonFormatter()

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

file_handler = logging.FileHandler("yeti.log")
file_handler.setFormatter(formatter)

listener = QueueListener(log_queue, console_handler, file_handler)
listener.start()
logger.setLevel(logging.INFO)

logging.getLogger("uvicorn.access").disabled = True

