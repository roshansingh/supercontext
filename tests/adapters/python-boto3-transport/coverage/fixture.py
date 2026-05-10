import boto3


def publish_order():
    client = boto3.client("sqs")
    client.send_message(QueueUrl=get_queue_url(), MessageBody="created")
