"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Users, Plus, Pencil, Trash2, X, Loader2, RefreshCw, Gamepad2 } from "lucide-react";
import { gameRequest, usePolling } from "./GamePage";
import ConfirmAction from "./ConfirmAction";

const ROLES = ["superuser", "user"];

export default function ConfigurePage({ c, me, onSelfChanged }) {
  return (
    <div className="rt-worker">
      <section className={`rt-panel min-w-0 rounded-xl p-4 ${c.card} ${c.title}`}>
        <UserTab c={c} me={me} onSelfChanged={onSelfChanged} />
      </section>
      <GamePlayers c={c} />
    </div>
  );
}

/* ── helpers ─────────────────────────────────────────────────────── */

/** "2026-11-12 21:23:31.193634" → "2026-11-12 21:23:31" */
const toDisplay = (v) => (v ? v.slice(0, 19) : "—");

async function api(path, init) {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function RoleBadge({ c, role }) {
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${role === "superuser" ? c.badgeSuper : c.badgeUser}`}>
      {role || "—"}
    </span>
  );
}

/* ── User tab ────────────────────────────────────────────────────── */

function UserTab({ c, me, onSelfChanged }) {
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(null);   // null | { mode: "create" } | { mode: "edit", user }
  const [deleting, setDeleting] = useState(null); // username being deleted

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { setUsers((await api("/api/users")).users); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function remove(u) {
    if (!window.confirm(`Delete user "${u.username}"? This can't be undone.`)) return;
    setDeleting(u.username); setError("");
    try {
      await api(`/api/users/${encodeURIComponent(u.username)}`, { method: "DELETE" });
      setUsers((list) => list.filter((x) => x.username !== u.username));
    } catch (e) { setError(e.message); }
    finally { setDeleting(null); }
  }

  function saved(user, prevUsername) {
    setEditing(null);
    if (prevUsername === me.username) onSelfChanged();
    load();
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2.5 text-lg font-semibold tracking-tight">
            <Users size={18} aria-hidden="true" className="text-[color:var(--accent)]" /> Dashboard users
          </h2>
          <p className={`text-xs ${c.muted}`}>
            {users ? `${users.length} account${users.length === 1 ? "" : "s"}` : "Loading…"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={load} disabled={loading} aria-label="Refresh accounts"
            className="rt-icon-button">
            <RefreshCw size={16} aria-hidden="true" className={loading ? "animate-spin" : ""} />
          </button>
          <button type="button" onClick={() => setEditing({ mode: "create" })} className="rt-button">
            <Plus size={16} strokeWidth={2.25} aria-hidden="true" /> Add user
          </button>
        </div>
      </div>

      {error && <p role="alert" className={`rounded-lg px-3 py-2 text-xs ${c.error}`}>{error}</p>}

      <div tabIndex={0} role="region" aria-label="Dashboard users table" className="rt-table-scroll overflow-x-auto rounded-lg">
        <table className="w-full min-w-[425px] text-left text-xs">
          <thead className={`text-xs uppercase tracking-wide ${c.tableHead}`}>
            <tr>
              <th className="px-3 py-2.5 font-medium">Username</th>
              <th className="px-3 py-2.5 font-medium">Role</th>
              <th className="px-3 py-2.5 font-medium">Account activity</th>
              <th className="px-3 py-2.5 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users?.map((u) => (
              <tr key={u.username} className={`transition ${c.tableRow}`}>
                <td className="px-3 py-2.5 font-medium">
                  {u.username}
                  {u.username === me.username && <span className={`ml-2 text-xs ${c.muted}`}>(you)</span>}
                  {u.nickname && <span className={`block font-normal ${c.label}`}>{u.nickname}</span>}
                </td>
                <td className="px-3 py-2.5"><RoleBadge c={c} role={u.role} /></td>
                <td className="px-3 py-2.5 tabular-nums">
                  <div>Created {toDisplay(u.created_at)}</div>
                  <div className={c.label}>Last login {toDisplay(u.last_login)}</div>
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex justify-end gap-2">
                    <button onClick={() => setEditing({ mode: "edit", user: u })}
                      title={`Edit ${u.username}`} aria-label={`Edit ${u.username}`}
                      className={`rt-icon-button ${c.iconBtn}`}>
                      <Pencil size={15} aria-hidden="true" />
                    </button>
                    <button onClick={() => remove(u)} disabled={u.username === me.username || deleting === u.username}
                      title={u.username === me.username ? "You can't delete yourself" : `Delete ${u.username}`}
                      aria-label={`Delete ${u.username}`}
                      className={`rt-icon-button disabled:opacity-40 ${c.iconBtnDanger}`}>
                      {deleting === u.username ? <Loader2 size={15} aria-hidden="true" className="animate-spin" /> : <Trash2 size={15} aria-hidden="true" />}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {users?.length === 0 && (
              <tr className={c.tableRow}><td colSpan={4} className={`px-3 py-8 text-center ${c.muted}`}>No users yet.</td></tr>
            )}
            {!users && (
              <tr className={c.tableRow}><td colSpan={4} className={`px-3 py-8 text-center ${c.muted}`}>
                {loading ? "Loading users…" : "—"}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {editing && (
        <UserModal c={c} editing={editing} me={me} onClose={() => setEditing(null)} onSaved={saved} />
      )}
    </div>
  );
}

function UserModal({ c, editing, me, onClose, onSaved }) {
  const isEdit = editing.mode === "edit";
  const orig = editing.user || {};
  const roleLocked = isEdit && orig.username === me.username && me.role === "superuser";
  const [form, setForm] = useState({
    username:   orig.username || "",
    nickname:   orig.nickname || "",
    password:   "",
    role:       orig.role || "user",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialogRef = useRef(null);
  const usernameRef = useRef(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog.showModal();
    usernameRef.current.focus();
    return () => dialog.close();
  }, []);

  function dismiss() {
    dialogRef.current.close();
    onClose();
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError("");
    const body = { username: form.username, nickname: form.nickname, password: form.password, role: form.role };
    try {
      const { user } = await api(isEdit ? `/api/users/${encodeURIComponent(orig.username)}` : "/api/users", {
        method: isEdit ? "PUT" : "POST",
        body: JSON.stringify(body),
      });
      dialogRef.current.close();
      onSaved(user, orig.username);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  const field = `h-10 w-full rounded-lg px-3 text-sm outline-none transition ${c.input}`;
  const lbl = `mb-1 block text-xs font-medium ${c.label}`;

  return (
    <dialog ref={dialogRef} className={`rt-dialog rounded-xl ${c.modal}`} aria-labelledby="user-modal-title"
      onCancel={(event) => { event.preventDefault(); dismiss(); }}>
      <form onSubmit={submit} className="p-4 sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="user-modal-title" className="text-xl font-semibold tracking-tight">
            {isEdit ? `Edit user "${orig.username}"` : "Add user"}
          </h2>
          <button type="button" onClick={dismiss} aria-label="Close" className="rt-icon-button"><X size={18} aria-hidden="true" /></button>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="sm:col-span-1">
            <span className={lbl}>Username *</span>
            <input ref={usernameRef} className={field} value={form.username} onChange={set("username")} required
              autoComplete="off" maxLength={64} />
          </label>
          <label>
            <span className={lbl}>Nickname</span>
            <input className={field} value={form.nickname} onChange={set("nickname")} maxLength={100} />
          </label>
          <label>
            <span className={lbl}>Password {isEdit ? "" : "*"}</span>
            <input className={field} type="password" value={form.password} onChange={set("password")}
              autoComplete="new-password" maxLength={72} required={!isEdit}
              placeholder={isEdit ? "Leave blank to keep current" : ""} />
          </label>
          <label>
            <span className={lbl}>Role *</span>
            <select className={field} value={form.role} disabled={roleLocked} onChange={set("role")}
              aria-describedby={roleLocked ? "own-role-help" : undefined}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            {roleLocked && <span id="own-role-help" className={`mt-1 block text-xs ${c.label}`}>Your role is locked.</span>}
          </label>
        </div>

        {error && <p role="alert" className={`mt-3 rounded-lg px-3 py-2 text-xs ${c.error}`}>{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={dismiss} className={`rounded-lg px-4 text-sm font-semibold ${c.btnGhost}`}>
            Cancel
          </button>
          <button type="submit" disabled={busy} className="rt-button">
            {busy && <Loader2 size={14} aria-hidden="true" className="animate-spin" />}
            {busy ? "Saving…" : isEdit ? "Save changes" : "Create user"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

function GamePlayers({ c }) {
  const [refresh, setRefresh] = useState(0);
  const { data, error } = usePolling("players", 5000, refresh);
  const { data: overview } = usePolling("overview", 3000, refresh);
  const [target, setTarget] = useState(null);
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const result = overview?.operation;
    if (!pending || result?.id !== pending.id || result.status === "pending") return;
    if (result.status === "applied") setNotice(`Gameplay data reset for ${pending.username}.`);
    else setFailure(result.message || "The reset could not be confirmed.");
    setPending(null);
    setRefresh((count) => count + 1);
  }, [pending, overview]);

  async function reset() {
    const username = target;
    setTarget(null);
    setBusy(true);
    setFailure("");
    setNotice("");
    try {
      const { operation } = await gameRequest("player-reset", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, confirm: "player-reset" }),
      });
      setPending({ id: operation.id, username });
      setNotice(`Waiting for the game to confirm the reset for ${username}.`);
      setRefresh((count) => count + 1);
    } catch (problem) {
      setFailure(problem.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`rt-panel grid min-w-0 gap-3 rounded-xl p-4 ${c.card} ${c.title}`}>
      <div>
        <h2 className="flex items-center gap-2.5 text-lg font-semibold">
          <Gamepad2 size={18} className="text-[color:var(--accent)]" aria-hidden="true" /> In-game players
        </h2>
        <p className={`text-xs ${c.label}`}>Reset a player’s save, settlements and sites. Their game login remains available.</p>
      </div>
      {(failure || error) && <p role="alert" className={`rounded-lg p-2 text-sm ${c.error}`}>{failure || error}</p>}
      {notice && !failure && <p role="status" className={`text-sm ${c.label}`}>{notice}</p>}
      {data?.players.length ? (
        <div tabIndex={0} role="region" aria-label="In-game player table" className="overflow-x-auto">
          <table className="w-full min-w-[340px] text-left text-xs">
            <thead className={c.tableHead}><tr>
              <th className="p-2" scope="col">Player / colony</th>
              <th className="p-2" scope="col">Settlements / last save</th>
              <th className="p-2 text-right" scope="col">Action</th>
            </tr></thead>
            <tbody>{data.players.map((player) => (
              <tr key={player.username} className={c.tableRow}>
                <th className="break-all p-2" scope="row">{player.username}
                  {player.colony_name && <span className={`block font-normal ${c.label}`}>{player.colony_name}</span>}
                </th>
                <td className="p-2">
                  {player.settlement_tiles.length}
                  <span className={`block ${c.label}`}>{player.last_save ? new Date(player.last_save).toLocaleString() : "No active save"}</span>
                </td>
                <td className="p-2 text-right">
                  <button type="button" onClick={() => setTarget(player.username)}
                    disabled={!player.can_reset || busy || Boolean(pending) || overview?.status !== "ready" || overview?.operation?.status === "pending"}
                    aria-label={`Reset gameplay data for ${player.username}`}
                    className="rt-button rt-danger-button">Reset data</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className={`text-sm ${c.label}`}>{data ? "No players have registered in-game yet." : "Loading game players…"}</p>}
      {target && <ConfirmAction c={c} title={`Reset gameplay data for ${target}?`} label="Confirm player reset"
        message="The game disconnects this player, backs up their gameplay data, and removes their active save, settlements and sites."
        onCancel={() => setTarget(null)} onConfirm={reset} />}
    </section>
  );
}
