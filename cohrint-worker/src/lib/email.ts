/**
 * Email helper via Resend API.
 * Set RESEND_API_KEY as a Cloudflare Worker secret:
 *   wrangler secret put RESEND_API_KEY
 */

import { createLogger } from './logger';
import { withBreaker } from './circuit';

interface EmailOptions {
  to:      string;
  subject: string;
  html:    string;
}

export async function sendEmail(
  resendKey: string | undefined,
  opts: EmailOptions,
  kv?: KVNamespace,
): Promise<void> {
  if (!resendKey) {
    createLogger(crypto.randomUUID()).warn('sendEmail: RESEND_API_KEY not configured — email not sent', { to: opts.to, subject: opts.subject });
    return;
  }

  const headers = {
    'Authorization': `Bearer ${resendKey}`,
    'Content-Type': 'application/json',
  };

  const doSend = async (): Promise<void> => {
    const log = createLogger(crypto.randomUUID());
    // Try verified domain first; fall back to Resend shared domain if not yet verified
    const senders = [
      'Cohrint <noreply@cohrint.com>',
      'Cohrint <onboarding@resend.dev>',
    ];
    for (const from of senders) {
      const res = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers,
        body: JSON.stringify({ from, to: opts.to, subject: opts.subject, html: opts.html }),
      });
      if (res.ok) return;
      const body = await res.json() as { name?: string; message?: string };
      if (body.name !== 'validation_error') {
        throw new Error(`Resend error: ${body.name ?? 'unknown'} — ${body.message ?? res.status}`);
      }
      log.warn('sendEmail: domain not verified, retrying with shared sender', { from });
    }
    throw new Error('sendEmail: all senders failed');
  };

  if (kv) {
    const result = await withBreaker('resend', kv, doSend);
    if (result === null) {
      createLogger(crypto.randomUUID()).warn('sendEmail skipped — Resend circuit breaker open');
    }
  } else {
    try {
      await doSend();
    } catch (err) {
      createLogger(crypto.randomUUID()).warn('sendEmail failed', { err: String(err) });
    }
  }
}

// ── Email templates ───────────────────────────────────────────────────────────

export function memberInviteEmail(opts: {
  invitedBy: string;
  orgId:     string;
  orgName:   string;
  role:      string;
  scopeTeam: string | null;
  apiKey:    string;
  keyHint:   string;
}): { subject: string; html: string } {
  const dashUrl = `https://cohrint.com/app.html?api_key=${opts.apiKey}&org=${opts.orgId}`;
  return {
    subject: `You've been invited to ${opts.orgName} on Cohrint`,
    html: `
<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1a1a1a">
  <div style="margin-bottom:24px">
    <img src="https://cohrint.com/og-image.png" alt="Cohrint" style="height:28px">
  </div>
  <h2 style="font-size:20px;margin:0 0 8px">You've been invited</h2>
  <p style="color:#555;margin:0 0 20px"><strong>${opts.invitedBy}</strong> has added you to
    <strong>${opts.orgName}</strong> on Cohrint as <strong>${opts.role}</strong>
    ${opts.scopeTeam ? `(scoped to team: <strong>${opts.scopeTeam}</strong>)` : ''}.
  </p>

  <div style="background:#f4f4f4;border-radius:8px;padding:16px;margin-bottom:20px">
    <div style="font-size:11px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Your API key — shown once, store securely</div>
    <code style="font-size:13px;word-break:break-all;color:#111">${opts.apiKey}</code>
  </div>

  <div style="background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:12px;font-size:13px;color:#795548;margin-bottom:20px">
    ⚠️ This key will not be shown again. Copy it now and store it in a password manager or environment variable.
  </div>

  <a href="${dashUrl}" style="display:inline-block;background:#00d4a1;color:#000;padding:11px 22px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px;margin-bottom:20px">
    Open Dashboard →
  </a>

  <div style="font-size:12px;color:#888;border-top:1px solid #eee;padding-top:16px;margin-top:8px">
    <strong>Quick start:</strong><br>
    <code style="font-size:11px">pip install cohrint</code> or
    <code style="font-size:11px">npm install cohrint</code><br><br>
    Questions? Reply to this email or visit <a href="https://cohrint.com/docs.html">docs</a>.
  </div>
</div>`,
  };
}

export function keyRecoveryEmail(opts: {
  orgId:      string;
  orgName:    string;
  keyHint:    string;
  isOwner:    boolean;
  redeemUrl?: string;
}): { subject: string; html: string } {
  return {
    subject: 'Cohrint — API key recovery',
    html: `
<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1a1a1a">
  <h2 style="font-size:20px;margin:0 0 12px">API key recovery</h2>
  <p style="color:#555;margin:0 0 16px">
    We received a recovery request for <strong>${opts.orgName}</strong> (org: <code>${opts.orgId}</code>).
  </p>

  <div style="background:#f4f4f4;border-radius:8px;padding:16px;margin-bottom:16px">
    <div style="font-size:11px;color:#888;margin-bottom:4px">Current key hint</div>
    <code style="font-size:14px">${opts.keyHint}</code>
  </div>

  ${opts.isOwner && opts.redeemUrl ? `
  <div style="background:#e8fdf5;border:1px solid #00d4a1;border-radius:8px;padding:16px;margin-bottom:20px">
    <p style="margin:0 0 12px;font-size:14px;color:#111">
      <strong>Click below to get a new API key instantly.</strong><br>
      Your old key will be revoked and a new one issued — you'll be signed in automatically.
    </p>
    <a href="${opts.redeemUrl}" style="display:inline-block;background:#00d4a1;color:#000;padding:11px 22px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px">
      Get a new API key →
    </a>
    <p style="margin:12px 0 0;font-size:11px;color:#888">This link expires in 1 hour and can only be used once.</p>
  </div>
  ` : opts.isOwner ? `
  <p style="color:#555;font-size:14px">
    <strong>Your recovery link could not be generated.</strong><br>
    Please request a new recovery email — the link is valid for 1 hour.
  </p>
  <a href="https://cohrint.com/auth" style="display:inline-block;background:#00d4a1;color:#000;padding:11px 22px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px;margin-bottom:20px">
    Try again →
  </a>
  ` : `
  <p style="color:#555;font-size:14px">
    <strong>To get a new key:</strong><br>
    Ask your org admin to revoke and re-issue your member key.
  </p>
  <a href="https://cohrint.com/auth" style="display:inline-block;background:#00d4a1;color:#000;padding:11px 22px;border-radius:7px;text-decoration:none;font-weight:600;font-size:14px;margin-bottom:20px">
    Sign in →
  </a>
  `}

  <div style="font-size:12px;color:#aaa;border-top:1px solid #eee;padding-top:16px;margin-top:8px">
    If you didn't request this, you can safely ignore this email. Your key remains unchanged unless you click the link above.
  </div>
</div>`,
  };
}
