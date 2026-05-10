import boto3


def publish_order():
    client = boto3.client("sqs")
    client.send_message(
        QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789012/orders",
        MessageBody="created",
    )
