// Desktop notification layer.
//
// In Tauri:  uses the native notification plugin → real Windows toast.
// In browser (dev mode): uses the Web Notification API → real Windows toast
//                        (when running in Edge app-mode, Edge surfaces them
//                        as standard system notifications).

const IN_TAURI = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let permGranted: boolean | null = null;

export async function ensurePermission(): Promise<boolean> {
  if (permGranted !== null) return permGranted;
  if (IN_TAURI) {
    const { isPermissionGranted, requestPermission } = await import("@tauri-apps/plugin-notification");
    let ok = await isPermissionGranted();
    if (!ok) {
      const p = await requestPermission();
      ok = p === "granted";
    }
    permGranted = ok;
    return ok;
  }
  if (typeof Notification === "undefined") {
    permGranted = false;
    return false;
  }
  if (Notification.permission === "granted") {
    permGranted = true;
    return true;
  }
  if (Notification.permission === "denied") {
    permGranted = false;
    return false;
  }
  const p = await Notification.requestPermission();
  permGranted = p === "granted";
  return permGranted;
}

export async function notify(opts: { title: string; body: string; icon?: string }) {
  const ok = await ensurePermission();
  if (!ok) {
    console.warn("notification permission not granted");
    return;
  }
  if (IN_TAURI) {
    const { sendNotification } = await import("@tauri-apps/plugin-notification");
    sendNotification({ title: opts.title, body: opts.body, icon: opts.icon });
  } else if (typeof Notification !== "undefined") {
    new Notification(opts.title, { body: opts.body, icon: opts.icon ?? "/icon.svg" });
  }
}

export async function notifyReply(opts: {
  from: string;
  subject: string;
  sequence: string;
  snippet: string;
}) {
  await notify({
    title: `↩ Reply from ${opts.from}`,
    body: `${opts.subject}\n\n${opts.snippet}\n\nSequence "${opts.sequence}" auto-paused.`,
    icon: "/icon.svg",
  });
}
