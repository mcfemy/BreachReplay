import json
import os
import boto3

INSTANCE_ID = os.environ["INSTANCE_ID"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

ec2 = boto3.client("ec2", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>BreachReplay — Waking Up</title>
  <meta http-equiv="refresh" content="90;url=https://breachreplay.com">
  <style>
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
           display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
    .card { text-align: center; max-width: 420px; padding: 2rem; }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; color: #f97316; }
    p { color: #94a3b8; line-height: 1.6; }
    .spinner { width: 40px; height: 40px; border: 3px solid #334155;
               border-top-color: #f97316; border-radius: 50%;
               animation: spin 1s linear infinite; margin: 1.5rem auto; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h1>BreachReplay is starting...</h1>
    <p>The server is spinning up. You'll receive an email when it's ready (~2 min).<br>
       This page auto-redirects when it's live.</p>
  </div>
</body>
</html>"""


def lambda_handler(event, context):
    try:
        resp = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
        state = resp["Reservations"][0]["Instances"][0]["State"]["Name"]
    except Exception as e:
        return _html(f"Error checking instance: {e}", 500)

    if state == "running":
        return {
            "statusCode": 302,
            "headers": {"Location": "https://breachreplay.com"},
            "body": "",
        }

    if state in ("stopping", "shutting-down", "terminated"):
        return _html(f"Instance is currently {state}. Try again in a minute.", 503)

    if state == "stopped":
        ec2.start_instances(InstanceIds=[INSTANCE_ID])
        try:
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject="BreachReplay is starting",
                Message=(
                    "Your BreachReplay instance is waking up.\n\n"
                    "It will be ready at https://breachreplay.com in about 2 minutes."
                ),
            )
        except Exception:
            pass  # email failure is non-fatal

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html"},
        "body": HTML,
    }


def _html(msg, status):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/html"},
        "body": f"<h1>{msg}</h1>",
    }
