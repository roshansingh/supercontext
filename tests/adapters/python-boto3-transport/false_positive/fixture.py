def send_message(queue_url, body):
    return f"{queue_url}:{body}"
