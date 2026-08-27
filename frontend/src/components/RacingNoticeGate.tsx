/**
 * Phase 4 — first-use notice before ghost racing or sharing a run.
 * Persisted server-side via User.has_acknowledged_racing_notice (sibling of
 * has_seen_console_intro). Shown once per account, not on every race/share.
 */
import { useCallback, useState } from "react";
import { axiosInstance } from "../lib/api";
import { useAuthStore } from "../store/auth";

export function RacingNoticeDialog({
  open,
  onConfirm,
  onCancel,
  busy,
}: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/70"
      role="dialog"
      aria-modal="true"
      aria-labelledby="racing-notice-title"
    >
      <div className="max-w-md w-full rounded-lg border border-breach-border bg-breach-surface p-6 shadow-xl">
        <h2 id="racing-notice-title" className="text-breach-text text-sm uppercase tracking-wider font-semibold mb-3">
          Racing &amp; sharing
        </h2>
        <p className="text-breach-muted text-sm leading-relaxed mb-4">
          Racing shares your run publicly and may email other players when you beat their containment time.
          Anyone with a share link can view your run and race against it.
        </p>
        <p className="text-breach-muted text-xs mb-6">
          <a href="/privacy" className="text-phosphor hover:text-white underline">
            Learn more
          </a>{" "}
          in our Privacy Policy.
        </p>
        <div className="flex gap-3 justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2 text-xs uppercase tracking-widest text-breach-muted border border-breach-border rounded hover:text-breach-text disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="px-4 py-2 text-xs uppercase tracking-widest text-white bg-breach-accent rounded hover:bg-red-600 disabled:opacity-50"
          >
            {busy ? "Saving…" : "Got it"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function useRacingNotice() {
  const user = useAuthStore((s) => s.user);
  const updateUser = useAuthStore((s) => s.updateUser);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingResolve, setPendingResolve] = useState<((ok: boolean) => void) | null>(null);

  const ensureAcknowledged = useCallback((): Promise<boolean> => {
    if (!user) return Promise.resolve(true);
    if (user.has_acknowledged_racing_notice) return Promise.resolve(true);
    return new Promise((resolve) => {
      setPendingResolve(() => resolve);
      setOpen(true);
    });
  }, [user]);

  const handleCancel = useCallback(() => {
    setOpen(false);
    pendingResolve?.(false);
    setPendingResolve(null);
  }, [pendingResolve]);

  const handleConfirm = useCallback(async () => {
    setBusy(true);
    try {
      const { data } = await axiosInstance.patch<{ has_acknowledged_racing_notice: boolean }>(
        "/auth/me",
        { has_acknowledged_racing_notice: true },
      );
      updateUser({ has_acknowledged_racing_notice: data.has_acknowledged_racing_notice });
      setOpen(false);
      pendingResolve?.(true);
      setPendingResolve(null);
    } catch {
      pendingResolve?.(false);
      setPendingResolve(null);
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }, [pendingResolve, updateUser]);

  const dialog = (
    <RacingNoticeDialog
      open={open}
      onConfirm={() => void handleConfirm()}
      onCancel={handleCancel}
      busy={busy}
    />
  );

  return { ensureAcknowledged, dialog };
}
