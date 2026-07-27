// Cloudflare Worker: sits in front of breachreplay.com (proxied DNS record).
// Proxies straight through to the EC2 origin while it's up. When the origin
// is unreachable (instance stopped by the CloudWatch idle alarm), it signs
// and sends its own ec2:StartInstances call directly to the AWS API — no
// Lambda, no public AWS endpoint of any kind — and serves visitors a
// "waking up" page that auto-retries until the origin responds again.
//
// Required Worker environment:
//   AWS_ACCESS_KEY_ID     (secret) - cloudflare-worker-wake IAM user
//   AWS_SECRET_ACCESS_KEY (secret) - same user; ec2:StartInstances on this
//                                    one instance only, nothing else
//   ORIGIN_IP             (plain var) - the EC2 Elastic IP, e.g. 32.195.1.149

const REGION = "us-east-1";
const INSTANCE_ID = "i-0b33d84fe18ea2c77";
const EC2_HOST = `ec2.${REGION}.amazonaws.com`;
const WAKE_LOCK_URL = "https://internal.invalid/wake-lock";
const WAKE_LOCK_TTL_SECONDS = 30;

export default {
  async fetch(request, env, ctx) {
    let originResponse = null;
    try {
      originResponse = await fetchOrigin(request, env);
    } catch (err) {
      originResponse = null;
    }

    if (originResponse) {
      if (originResponse.webSocket) {
        return new Response(null, { status: 101, webSocket: originResponse.webSocket });
      }
      return originResponse;
    }

    ctx.waitUntil(triggerWakeOnce(env, ctx));
    return holdingPageResponse();
  },
};

// Bypasses Cloudflare's proxy for this same hostname via resolveOverride —
// a plain fetch(request) here would re-enter this Worker's own route and
// loop forever, since the A record is proxied.
async function fetchOrigin(request, env) {
  const url = new URL(request.url);
  const hasBody = !["GET", "HEAD"].includes(request.method);

  return fetch(url.toString(), {
    method: request.method,
    headers: request.headers,
    body: hasBody ? request.body : undefined,
    redirect: "manual",
    cf: { resolveOverride: env.ORIGIN_IP },
    signal: AbortSignal.timeout(6000),
  });
}

async function triggerWakeOnce(env, ctx) {
  const cache = caches.default;
  const lockRequest = new Request(WAKE_LOCK_URL);

  if (await cache.match(lockRequest)) {
    return; // another request already triggered the wake within the TTL
  }
  await cache.put(
    lockRequest,
    new Response("locked", { headers: { "Cache-Control": `max-age=${WAKE_LOCK_TTL_SECONDS}` } })
  );

  try {
    await startInstance(env);
  } catch (err) {
    // Swallow — nothing useful to do with a failed wake call from here.
    // Next visitor's request will simply retry once the lock expires.
  }
}

async function startInstance(env) {
  const body = new URLSearchParams({
    Action: "StartInstances",
    Version: "2016-11-15",
    "InstanceId.1": INSTANCE_ID,
  }).toString();

  const signed = await signRequest({
    accessKeyId: env.AWS_ACCESS_KEY_ID,
    secretAccessKey: env.AWS_SECRET_ACCESS_KEY,
    region: REGION,
    service: "ec2",
    host: EC2_HOST,
    method: "POST",
    path: "/",
    body,
  });

  return fetch(`https://${EC2_HOST}/`, {
    method: "POST",
    headers: signed.headers,
    body,
  });
}

function holdingPageResponse() {
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>Waking up — BreachReplay</title>
<style>
  body { font-family: system-ui, sans-serif; background: #0b0f14; color: #e6edf3;
         display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
  .card { text-align: center; max-width: 28rem; padding: 2rem; }
  h1 { font-size: 1.25rem; margin-bottom: 0.5rem; }
  p { color: #9aa7b2; font-size: 0.95rem; }
  .spinner { width: 2rem; height: 2rem; margin: 0 auto 1.5rem; border-radius: 50%;
             border: 3px solid #263241; border-top-color: #4fd1c5; animation: spin 0.9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h1>BreachReplay is waking up</h1>
    <p>This page will refresh automatically — usually takes under a minute.</p>
  </div>
</body>
</html>`;

  return new Response(html, {
    status: 503,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "retry-after": "10",
      "cache-control": "no-store",
    },
  });
}

// --- AWS Signature Version 4 (minimal, POST + form-encoded body only) ---
// No external dependencies on purpose: this file is meant to be pasted
// directly into the Cloudflare dashboard's Worker editor.

async function signRequest({ accessKeyId, secretAccessKey, region, service, host, method, path, body }) {
  const now = new Date();
  const amzDate = now.toISOString().replace(/[:-]|\.\d{3}/g, "");
  const dateStamp = amzDate.slice(0, 8);

  const payloadHash = await sha256Hex(body);
  const canonicalHeaders =
    `content-type:application/x-www-form-urlencoded\n` +
    `host:${host}\n` +
    `x-amz-date:${amzDate}\n`;
  const signedHeaders = "content-type;host;x-amz-date";

  const canonicalRequest = [
    method,
    path,
    "", // no query string
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join("\n");

  const credentialScope = `${dateStamp}/${region}/${service}/aws4_request`;
  const stringToSign = [
    "AWS4-HMAC-SHA256",
    amzDate,
    credentialScope,
    await sha256Hex(canonicalRequest),
  ].join("\n");

  const signingKey = await getSignatureKey(secretAccessKey, dateStamp, region, service);
  const signature = toHex(await hmac(new Uint8Array(signingKey), stringToSign));

  const authorization =
    `AWS4-HMAC-SHA256 Credential=${accessKeyId}/${credentialScope}, ` +
    `SignedHeaders=${signedHeaders}, Signature=${signature}`;

  return {
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      host,
      "x-amz-date": amzDate,
      authorization,
    },
  };
}

// keyBytes must be raw key material (Uint8Array/ArrayBuffer), not a string —
// keeps this function's contract unambiguous, unlike a version that overloads
// "string means passphrase, anything else means raw bytes".
async function hmac(keyBytes, message) {
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  return crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(message));
}

async function getSignatureKey(secretAccessKey, dateStamp, region, service) {
  const kSecret = new TextEncoder().encode(`AWS4${secretAccessKey}`);
  const kDate = await hmac(kSecret, dateStamp);
  const kRegion = await hmac(new Uint8Array(kDate), region);
  const kService = await hmac(new Uint8Array(kRegion), service);
  const kSigning = await hmac(new Uint8Array(kService), "aws4_request");
  return kSigning;
}

async function sha256Hex(message) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(message));
  return toHex(digest);
}

function toHex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
