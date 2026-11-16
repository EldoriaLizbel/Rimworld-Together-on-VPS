"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { Activity, CheckCircle2, Circle, RotateCw, Save, ScrollText, Settings2, Users } from "lucide-react";
import { configHelp, fieldDependency } from "./gameConfigHelp";
import ConfirmAction from "./ConfirmAction";

const endpoint = "/api/game/";
const minute = 60000;
const states = {
  ready: ["Ready", "text-[color:var(--success)]"],
  starting: ["Starting", "text-[color:var(--warn)]"],
  restarting: ["Restarting", "text-[color:var(--warn)]"],
  failed: ["Startup failed", "text-[color:var(--danger)]"],
  stopped: ["Stopped", "text-[color:var(--muted)]"],
  offline: ["Offline", "text-[color:var(--muted)]"],
};

const fileLabels = {
  "Configs/ServerConfig.json": "Server rules",
  "Configs/ChatConfig.json": "Chat and notifications",
  "Configs/BackupConfig.json": "Backups",
  "Configs/DifficultyConfig.json": "Game difficulty",
  "Configs/StorytellerConfig.json": "Storyteller",
  "Configs/ScenarioConfig.json": "Starting scenario",
  "Configs/ModConfig.json": "Mod policy",
  "Configs/Actions/Raid.json": "Player raids",
  "Configs/Actions/Trade.json": "Player trading",
  "Configs/Actions/Caravan.json": "Caravans",
  "Configs/Actions/Aid.json": "Player aid",
  "Configs/Actions/Event.json": "Player-sent events",
  "Configs/Actions/Market.json": "Marketplace",
  "Configs/Actions/Guild.json": "Guilds",
  "Configs/Actions/Site.json": "Sites",
  "Configs/Actions/Road.json": "Roads",
  "Configs/Actions/River.json": "Rivers",
  "Configs/Actions/Pollution.json": "Pollution",
  "Configs/Actions/Scenario.json": "Custom scenarios",
};

const labels = {
  Name: "Server name", Description: "Description", MaxPlayers: "Player limit",
  EnableMoTD: "Show welcome message", MessageOfTheDay: "Welcome message",
  LoginNotifications: "Announce login", DisconnectNotifications: "Announce disconnect",
  EnableServerBrowser: "List in the server browser", EnableServerTelemetry: "Server telemetry",
  DiscordURL: "Discord URL", SteamWorkshopURL: "Steam Workshop URL", Verbosity: "Console log level",
  DisplayChatInConsole: "Show chat in the server console", UseUPnP: "Request router port forwarding via UPnP",
  AutomaticBackups: "Enable automatic backups", IntervalHours: "Backup interval",
  AutomaticDeletion: "Automatically delete older backups", Amount: "Backups to keep",
  TimeInterval: "Reward interval", BuildingCost: "Site construction cost",
  RewardsCount: "Site reward quantity", MinimumPrice: "Minimum purchase price",
  PriceMultiplier: "Market price adjustment", MaxEntriesPerPlayer: "Maximum listings per player",
  IsDifficultyEnforced: "Enforce custom difficulty", IsEnforced: "Enforce selection",
  AllowAllMods: "Bypass mod requirements", EnforceSettings: "Enforce mod settings",
  IsEnabled: "Enabled for standard players", Cooldown: "Cooldown",
};

const passwordPattern = "[!-~]+";
const difficultyFile = "Configs/DifficultyConfig.json";
const customScenariosFile = "Configs/Actions/Scenario.json";
const worldFile = "Assets/WorldValuesFile.json";

function settingValue(settings, file, key) {
  return key.split(".").reduce((value, part) => value?.[part], settings[file]);
}

function fileLabel(file, settings) {
  if (file.startsWith("Assets/Events/")) return `Event: ${settings[file]?.Name || file.split("/").pop()}`;
  return fileLabels[file] || file;
}

function fieldLabel(file, key) {
  if (file.startsWith("Assets/Events/")) {
    return { Name: "Event name", Cost: "Event cost", IsEnabled: "Enable event" }[key];
  }
  if (file === customScenariosFile && key === "IsEnabled") return "Allow custom scenarios";
  return labels[key] || key.split(".").pop().replace(/([a-z0-9])([A-Z])/g, "$1 $2");
}

export async function gameRequest(path, options) {
  const response = await fetch(endpoint + path, { cache: "no-store", ...options });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Request failed");
  return result;
}

const request = gameRequest;

export function usePolling(path, interval = 4000, refresh = 0) {
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      clearTimeout(timer);
      try {
        const data = await request(path, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setResult({ path, data, checkedAt: new Date() });
          setFailure(null);
        }
      } catch (error) {
        if (!controller.signal.aborted) setFailure({ path, message: error.message });
      } finally {
        pending = false;
        if (!controller.signal.aborted) timer = setTimeout(refresh, interval);
      }
    }
    function onVisible() {
      if (document.visibilityState === "visible") refresh();
    }
    document.addEventListener("visibilitychange", onVisible);
    refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [path, interval, refresh]);
  return {
    data: result?.path === path ? result.data : null,
    checkedAt: result?.path === path ? result.checkedAt : null,
    error: failure?.path === path ? failure.message : "",
  };
}

function date(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function Feedback({ c, error }) {
  return error && <p role="alert" className={`rounded-lg px-3 py-2 text-sm ${c.error}`}>{error}</p>;
}

function PanelHeading({ Icon, children }) {
  return (
    <h2 className="flex items-center gap-2.5 text-lg font-semibold tracking-tight">
      <Icon size={18} strokeWidth={1.8} aria-hidden="true" className="shrink-0 text-[color:var(--accent)]" />
      {children}
    </h2>
  );
}

export function ServerOverview({ c, isAdmin }) {
  const { data, error } = usePolling("overview");
  if (!data) {
    return <div className={c.label}>{error ? <Feedback c={c} error={error} /> : "Loading server status…"}</div>;
  }
  const [status, color] = states[data.status] || states.offline;
  const { server } = data;
  const gameAddress = server.host_address.includes(":") ? `[${server.host_address}]` : server.host_address;
  return (
    <div className="grid gap-4">
      <Feedback c={c} error={error} />
      <section className={`rt-panel rounded-xl ${c.card} ${c.title}`}>
        <div className="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
          <div>
            <h2 className="break-words text-xl font-semibold tracking-tight sm:text-2xl">{server.name || "RimWorld Together"}</h2>
            {server.description && <p className={`mt-2 max-w-prose text-sm ${c.label}`}>{server.description}</p>}
          </div>
          <span role="status" className={`rt-status ${color}`}>
            {data.status === "ready" ? <CheckCircle2 size={14} aria-hidden="true" /> : <Circle size={10} aria-hidden="true" />} {status}
          </span>
        </div>
        <dl className="rt-metrics text-sm">
          {[
            ["Published address", `${gameAddress}:${server.host_port}`],
            ["Server bind", server.bind_ip ? `${server.bind_ip}:${server.port}` : "—"],
            ["Game version", data.version || "—"],
            ["Registered players", data.players],
            ["Player limit", server.max_players ?? "—"],
            ["World", data.world_initialized ? "Initialized" : "Awaiting world creation"],
            ["Last start", date(data.started_at)],
            ["Last heartbeat", date(data.heartbeat_at)],
          ].map(([key, value]) => (
            <div key={key}><dt className={`text-xs ${c.label}`}>{key}</dt><dd className="mt-1 break-words font-medium tabular-nums">{value}</dd></div>
          ))}
        </dl>
      </section>
      {isAdmin && (
        <div className="rt-panel-grid">
          <SettingsSnapshot c={c} />
          <PlayerActivity c={c} />
        </div>
      )}
    </div>
  );
}

function SettingsSnapshot({ c }) {
  const { data, error } = usePolling("config", minute);
  const [selection, setSelection] = useState("Configs/Actions/Raid.json");
  const settings = data?.snapshot?.settings || {};
  const files = Object.keys(settings);
  const file = files.includes(selection) ? selection : files[0];
  return (
    <section className={`rt-panel min-w-0 rounded-xl p-4 ${c.card} ${c.title}`}>
      <PanelHeading Icon={Settings2}>World and server settings</PanelHeading>
      <Feedback c={c} error={error} />
      {file ? (
        <>
          <select aria-label="Settings file" value={file} onChange={(event) => setSelection(event.target.value)}
            className={`mt-2 h-9 w-full rounded-md px-2 text-sm ${c.input}`}>
            {files.map((key) => <option key={key} value={key}>{fileLabel(key, settings)}</option>)}
          </select>
          <pre tabIndex={0} aria-label="Settings preview" className={`mt-2 max-h-56 overflow-auto rounded-md p-3 text-xs ${c.bg}`}>
            {JSON.stringify(settings[file], null, 2)}
          </pre>
        </>
      ) : <p className={`mt-2 text-sm ${c.label}`}>Settings will appear after the game server starts.</p>}
    </section>
  );
}

function SettingField({ c, file, fieldKey, rule, value, disabled, setValue }) {
  const id = useId();
  const [kind, limit, minimum = 1] = rule;
  const [help, unit] = configHelp(file, fieldKey);
  const isText = kind === "text" || kind === "url";
  const control = {
    id, disabled, "aria-describedby": [unit && `${id}-unit`, help && `${id}-help`].filter(Boolean).join(" ") || undefined,
  };
  const label = <label htmlFor={id} className="block break-words text-sm font-medium">{fieldLabel(file, fieldKey)}</label>;
  const description = help && <p id={`${id}-help`} className={`text-xs leading-snug ${c.label}`}>{help}</p>;
  if (kind === "boolean") {
    return (
      <div className="rt-config-toggle">
        <div className="min-w-0 space-y-1">{label}{description}</div>
        <label htmlFor={id} className="rt-config-switch">
          <input {...control} type="checkbox" role="switch" checked={value} className="sr-only"
            onChange={(event) => setValue(event.target.checked)} />
          <span aria-hidden="true" />
        </label>
      </div>
    );
  }
  const inputClass = `h-9 w-full min-w-0 rounded-md px-2 disabled:opacity-70 ${c.input}`;
  return (
    <div className="grid min-w-0 content-start gap-1">
      {label}
      {kind === "verbosity" ? (
        <select {...control} value={value} onChange={(event) => setValue(Number(event.target.value))} className={inputClass}>
          {["Normal", "Verbose", "Extreme"].map((name, index) => <option key={name} value={index}>{name}</option>)}
        </select>
      ) : (
        <div className="rt-config-value">
          <input {...control} value={value} className={inputClass}
            type={kind === "url" ? "url" : isText ? "text" : "number"}
            maxLength={isText ? limit : undefined}
            min={isText ? undefined : minimum} max={isText ? undefined : limit}
            step={kind === "decimal" ? "any" : undefined} required={!isText || fieldKey === "Name"}
            onChange={(event) => setValue(isText || event.target.value === "" ? event.target.value : event.target.valueAsNumber)} />
          {unit && <span id={`${id}-unit`} className={`text-xs ${c.label}`}>{unit}</span>}
        </div>
      )}
      {description}
    </div>
  );
}

const configCategories = [
  ["Server and backups", ["ServerConfig", "ChatConfig", "BackupConfig", "ModConfig"]],
  ["World and difficulty", ["DifficultyConfig", "StorytellerConfig", "ScenarioConfig", "Scenario"]],
  ["Player interactions", ["Raid", "Trade", "Caravan", "Aid", "Event", "Market", "Guild", "Site", "Road", "River", "Pollution"]],
  ["Individual events", []],
];
const changeKey = (file, key) => `${file}:${key}`;
const jsonPatch = (body) => ({ method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function GameConfig({ c }) {
  const [refresh, setRefresh] = useState(0);
  const { data, error } = usePolling("config", 4000, refresh);
  const { data: overview } = usePolling("overview", 4000, refresh);
  const [draft, setDraft] = useState({});
  const [base, setBase] = useState(null);
  const [operation, setOperation] = useState(null);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState(null);
  const [saved, setSaved] = useState(null);
  const snapshot = data?.snapshot;
  const staged = saved?.source === data ? saved?.staged : data?.staged;
  const savedFields = useMemo(() => Object.fromEntries((staged?.changes || []).map(({file, key, value}) =>
    [changeKey(file, key), value])), [staged]);
  const changes = Object.values(draft);
  const hasSaved = Boolean(staged?.id);
  const editable = Boolean(snapshot && !busy && !operation && !["pending", "waiting"].includes(overview?.operation?.status));
  const stale = changes.length > 0 && (base?.revision !== snapshot?.revision || base?.staged_id !== (staged?.id ?? null));
  const worldSeed = snapshot?.settings[worldFile]?.SeedString;

  useEffect(() => {
    const result = overview?.operation;
    if (!operation || result?.id !== operation) return;
    if (["rejected", "waiting"].includes(result.status) || overview.status === "failed") {
      setFailure(result.message || "The restart could not be confirmed. Check Server log.");
    } else if (result.status === "applied" && overview.status === "ready") {
      setNotice(result.kind === "factory-reset" ? "Official defaults restored. The game server is ready." : "The game server is ready.");
    } else {
      return;
    }
    setOperation(null);
    setRefresh((count) => count + 1);
  }, [operation, overview]);

  function setField(file, key, value) {
    if (!changes.length) setBase({ revision: snapshot.revision, staged_id: staged?.id ?? null });
    setDraft((items) => {
      const next = { ...items };
      const id = changeKey(file, key);
      if ((savedFields[id] ?? settingValue(snapshot.settings, file, key)) === value) delete next[id];
      else next[id] = { file, key, value };
      return next;
    });
  }

  async function submit(action) {
    setConfirmation(null);
    setFailure("");
    setNotice("");
    setBusy(true);
    const expected = staged?.id ? `?staged_id=${encodeURIComponent(staged.id)}` : "";
    try {
      if (action === "restart" || action === "factory-reset") {
        const result = await request(`${action}${expected}`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: action }),
        });
        setOperation(result.operation.id);
        setNotice(action === "factory-reset" ? "Factory reset requested. Waiting for the game server." : "Restart requested. Waiting for the game server.");
      } else {
        const result = action === "save" ? await request("config", jsonPatch({ ...base, changes }))
          : action === "discard" ? await request(`config${expected}`, { method: "DELETE" })
            : await request("password", jsonPatch({ password: action === "clear-password" ? "" : password }));
        setSaved({ source: data, staged: result.staged });
        setDraft({});
        setBase(null);
        if (action !== "save") setPassword("");
        setNotice(action === "discard" ? "Saved changes discarded." : result.staged.id
          ? "Saved. Restart the game server to apply the changes." : "Saved. The running settings already match.");
      }
      setRefresh((count) => count + 1);
    } catch (problem) {
      setFailure(problem.message);
    } finally {
      setBusy(false);
    }
  }

  const changedRetention = staged?.changes.some(({file, key}) =>
    file === "Configs/BackupConfig.json" && ["Amount", "AutomaticDeletion"].includes(key));
  const dialogs = {
    "factory-reset": {
      title: "Restore official defaults and restart?", label: "Confirm factory reset",
      message: "This replaces editable server settings, clears the game password and saved edits, disconnects players, and starts a new log history. " +
        "Official defaults enable public listing and telemetry. World data, saves, accounts, mod lists and individual event definitions are kept.",
    },
    restart: { title: "Restart the game server?", label: "Confirm restart",
      message: "Connected players will be disconnected. Ask them to save first." +
        (hasSaved ? " Saved settings will take effect, and a new server log history will begin." : "") +
        (changedRetention ? " Automatic deletion can remove older backups." : "") },
    discard: { title: "Discard saved changes?", label: "Discard saved changes",
      message: "This removes all settings and password changes waiting for a restart." },
    "clear-password": { title: "Remove the game access password?", label: "Save password removal",
      message: "Players will be able to join without a game password after the next restart." },
  };

  return (
    <div className="grid gap-4">
      <section className={`rt-panel rt-config-bar rounded-xl p-4 ${c.card} ${c.title}`} aria-label="Configuration actions">
        <div className="grid gap-1">
          <p className="text-sm font-semibold">{changes.length ? `${changes.length} unsaved change${changes.length === 1 ? "" : "s"}`
            : hasSaved ? "Saved changes awaiting restart" : "No changes awaiting restart"}</p>
          <p className={`break-words text-xs ${c.label}`}>{overview?.world_initialized
            ? <>Shared world seed{worldSeed ? <> <strong className="break-all">{worldSeed}</strong></> : " saved"}.</>
            : "The first player to create the world sets the shared map seed."}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {changes.length > 0 && <button type="button" onClick={() => { setDraft({}); setBase(null); }}
            className={`rounded-lg px-3 text-sm ${c.btnGhost}`}>Discard edits</button>}
          {hasSaved && !changes.length && <button type="button" disabled={!editable} onClick={() => setConfirmation("discard")}
            className={`rounded-lg px-3 text-sm ${c.btnGhost}`}>Discard saved changes</button>}
          <button type="submit" form="server-settings" disabled={!editable || !changes.length || stale} className="rt-button">
            <Save size={16} aria-hidden="true" /> Save changes
          </button>
          <button type="button" disabled={!editable || overview?.status !== "ready" || changes.length > 0 || Boolean(password)}
            onClick={() => setConfirmation("restart")} className="rt-button rt-danger-button">
            <RotateCw size={16} aria-hidden="true" /> Restart game server
          </button>
        </div>
        {(failure || error || stale) && <div className="col-span-full">
          <Feedback c={c} error={failure || error || "Settings changed while you were editing. Discard your edits to review the latest values."} />
        </div>}
        {notice && !failure && <p role="status" className={`col-span-full text-sm ${c.label}`}>{notice}</p>}
      </section>
      {snapshot ? (
        <form id="server-settings" onSubmit={(event) => { event.preventDefault(); if (editable && changes.length && !stale) submit("save"); }}
          className="grid gap-4">
          {configCategories.map(([label, names]) => {
            const files = names.length ? names.map((name) =>
              Object.keys(data.editable).find((file) => file.endsWith(`/${name}.json`) && file.startsWith("Configs/"))).filter(Boolean)
              : Object.keys(data.editable).filter((file) => file.startsWith("Assets/Events/"));
            if (!files.length) return null;
            const compact = files.filter((file) => Object.keys(data.editable[file]).length <= 8);
            const unpaired = compact.length % 2 === 1 ? compact.at(-1) : null;
            return (
              <section key={label} className={`rt-panel grid gap-3 rounded-xl p-4 ${c.card} ${c.title}`}>
                <PanelHeading Icon={Settings2}>{label}</PanelHeading>
                <div className="rt-config-groups">
                  {files.map((file) => {
                    const getValue = (key) => draft[changeKey(file, key)]?.value ?? savedFields[changeKey(file, key)]
                      ?? settingValue(snapshot.settings, file, key);
                    const fields = Object.entries(data.editable[file]).filter(([key]) => {
                      const dependency = fieldDependency(key);
                      return draft[changeKey(file, key)] || !dependency || getValue(dependency[0]) === dependency[1];
                    });
                    const selectionKey = { "Configs/StorytellerConfig.json": "DefName", "Configs/ScenarioConfig.json": "Name" }[file];
                    const selection = selectionKey && snapshot.settings[file]?.[selectionKey];
                    return (
                      <fieldset key={file} className={`rt-config-group ${compact.includes(file) && file !== unpaired ? "" : "rt-config-group-wide"}`}>
                        <legend className="px-1 text-sm font-semibold">{fileLabel(file, snapshot.settings)}</legend>
                        {selectionKey && <p className={`mb-2 break-words text-xs ${c.label}`}>
                          {selection ? `In-game selection: ${selection}` : "Select a value in RimWorld before enabling enforcement."}
                        </p>}
                        {file === difficultyFile && !getValue("IsDifficultyEnforced") && <p className={`mb-2 text-xs ${c.label}`}>
                          Difficulty values take effect when enforcement is enabled.
                        </p>}
                        <div className="rt-config-fields">
                          {fields.map(([key, rule]) => (
                            <SettingField key={key} c={c} file={file} fieldKey={key} rule={rule} value={getValue(key)}
                              disabled={!editable || Boolean(selectionKey && !selection && !getValue(key))}
                              setValue={(value) => setField(file, key, value)} />
                          ))}
                        </div>
                      </fieldset>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </form>
      ) : <p className={c.label}>Settings will appear after the game server starts.</p>}
      <section className={`rt-panel grid gap-3 rounded-xl p-4 ${c.card} ${c.title}`}>
        <PanelHeading Icon={Settings2}>Game access password</PanelHeading>
        <form onSubmit={(event) => { event.preventDefault(); if (editable && password && !changes.length) submit("password"); }}
          className="flex flex-wrap items-end gap-2">
          <div className="grid min-w-0 flex-1 basis-48 gap-1">
            <label htmlFor="game-access-password" className="text-sm font-medium">New game access password</label>
            <input id="game-access-password" disabled={!editable || changes.length > 0} type="password" autoComplete="new-password"
              pattern={passwordPattern} maxLength={64} required value={password} aria-describedby="game-password-help"
              onChange={(event) => setPassword(event.target.value)} className={`min-w-0 rounded-md px-2 ${c.input}`} />
          </div>
          <button type="submit" disabled={!editable || !password || changes.length > 0} className="rt-button">Save password</button>
          <button type="button" disabled={!editable || changes.length > 0} onClick={() => setConfirmation("clear-password")}
            className="rt-button rt-danger-button">Clear password</button>
        </form>
        <p id="game-password-help" className={`text-xs ${c.label}`}>
          Use printable ASCII characters without spaces. {staged?.password_pending
            ? "A saved password change awaits restart." : "Password changes take effect after restart."}
        </p>
      </section>
      <section className={`rt-panel flex flex-wrap items-center justify-between gap-3 rounded-xl p-4 ${c.card} ${c.title}`}>
        <div>
          <h2 className="text-sm font-semibold">Factory reset</h2>
          <p className={`text-xs ${c.label}`}>Restore the official configuration and restart the game server. World and player saves are kept.</p>
        </div>
        <button type="button" disabled={!editable || overview?.status !== "ready" || changes.length > 0 || Boolean(password)}
          onClick={() => setConfirmation("factory-reset")} className="rt-button rt-danger-button">Factory reset</button>
      </section>
      {confirmation && <ConfirmAction c={c} {...dialogs[confirmation]}
        onCancel={() => setConfirmation(null)} onConfirm={() => submit(confirmation)} />}
    </div>
  );
}

function PlayerActivity({ c }) {
  const { data, error } = usePolling("players");
  return (
    <section className={`rt-panel flex min-w-0 flex-col rounded-xl p-4 ${c.card} ${c.title}`}>
      <div className="mb-2"><PanelHeading Icon={Users}>Player activity</PanelHeading></div>
      <Feedback c={c} error={error} />
      {data?.players.length ? (
        <div className="rt-table-scroll max-h-64 overflow-auto" tabIndex={0} role="region" aria-label="Player activity table">
        <table className="w-full min-w-[420px] text-left text-xs">
          <thead className={c.tableHead}><tr>
            {["Player / colony", "Settlements / colonists", "Last login / save"].map((head) =>
              <th key={head} className="px-3 py-2" scope="col">{head}</th>)}
          </tr></thead>
          <tbody>{data.players.map((player) => (
            <tr key={player.username} className={c.tableRow}>
              <th className="px-3 py-2 font-semibold" scope="row">{player.username}
                <span className={`block font-normal ${c.label}`}>{player.colony_name ?? "—"}</span>
              </th>
              <td className="px-3 py-2">{player.settlement_tiles.join(", ") || "—"}
                <span className={`block ${c.label}`}>{player.colonist_count ?? "—"} colonists in save</span>
              </td>
              <td className="whitespace-nowrap px-3 py-2">{date(player.last_login)}
                <span className={`block ${c.label}`}>{date(player.last_save)}</span>
              </td>
            </tr>
          ))}</tbody>
        </table>
        </div>
      ) : (
        <div className={`rt-empty-state flex-1 text-sm ${c.label}`}>
          <Users size={24} strokeWidth={1.5} aria-hidden="true" />
          <p>{data ? "No player records yet." : "Loading player activity…"}</p>
        </div>
      )}
    </section>
  );
}

function ServerLogs({ c }) {
  const { data, error, checkedAt } = usePolling("logs", minute);
  const [pages, setPages] = useState(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState("");
  const older = pages?.epoch === data?.epoch ? pages : null;
  const entries = [...(data?.logs || []), ...(older?.logs || [])];
  const cursor = older ? older.next : data?.next;
  const seen = new Set();

  async function loadOlder() {
    setLoading(true);
    setFailure("");
    try {
      const result = await request(`logs?before=${cursor}`);
      setPages({ ...result, logs: [...(older?.logs || []), ...result.logs] });
    } catch (problem) {
      setFailure(problem.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className={`rt-panel rt-worker-panel rt-worker-log rounded-xl ${c.card} ${c.title}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <PanelHeading Icon={ScrollText}>Server log</PanelHeading>
        <p className={`text-xs ${c.label}`}>7-day history · Last checked {date(checkedAt)}</p>
      </div>
      <Feedback c={c} error={failure || error} />
      {entries.length ? (
        <div className="rt-table-scroll rt-log-viewport overflow-auto" tabIndex={0} role="region" aria-label="Server log table">
          <table className="w-full text-left text-xs">
            <thead className={c.tableHead}><tr>
              <th className="px-2 py-2" scope="col">Time</th>
              <th className="px-2 py-2" scope="col">Type</th>
              <th className="px-2 py-2" scope="col">Description</th>
            </tr></thead>
            <tbody>{entries.filter((entry) => !seen.has(entry.id) && seen.add(entry.id)).map((entry) => (
              <tr key={entry.id} className={c.tableRow}>
                <td className="px-2 py-2 align-top"><time dateTime={entry.occurred_at}>{date(entry.occurred_at)}</time></td>
                <td className="px-2 py-2 align-top capitalize">{entry.category}</td>
                <td className="break-words px-2 py-2 [overflow-wrap:anywhere]">
                  {entry.interpretation || entry.description}
                  {entry.interpretation && (
                    <details className={`mt-1 ${c.label}`}>
                      <summary className="cursor-pointer">Docker output</summary>
                      <div className="mt-1 font-mono">{entry.description}</div>
                    </details>
                  )}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className={c.label}>{data ? "There are no logs for this history yet." : "Loading server logs…"}</p>}
      {cursor && <button type="button" disabled={loading} onClick={loadOlder}
        className={`w-fit rounded-lg px-3 py-2 text-sm ${c.btnGhost}`}>Load older logs</button>}
    </section>
  );
}

const gibibytes = (bytes) => `${(bytes / 2 ** 30).toLocaleString(undefined, {
  minimumFractionDigits: 1, maximumFractionDigits: 1,
})} GiB`;

function HostResources({ c, host }) {
  const memory = host?.memory;
  return (
    <div className="grid gap-2 border-t border-[var(--border)] pt-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="text-sm font-semibold">Docker host resources</h3>
        <p className={`min-w-0 break-words text-xs ${c.label}`}>
          {[host?.cpu_model, host?.logical_cpus && `${host.logical_cpus} logical CPUs`, host?.architecture].filter(Boolean).join(" · ")
            || "CPU information unavailable."}
        </p>
      </div>
      {memory ? (
        <>
          <dl className="grid grid-cols-3 gap-2 text-xs">
            {[["RAM total", memory.total_bytes], ["RAM used", memory.used_bytes], ["RAM available", memory.available_bytes]].map(([label, value]) => (
              <div key={label} className={`min-w-0 rounded-md p-2 ${c.bg}`}>
                <dt className={c.label}>{label}</dt>
                <dd className="mt-1 break-words font-semibold tabular-nums">{gibibytes(value)}</dd>
              </div>
            ))}
          </dl>
          <meter className="block h-2 w-full" min={0} max={memory.total_bytes} value={memory.used_bytes}
            aria-label="RAM used" aria-valuetext={`${gibibytes(memory.used_bytes)} of ${gibibytes(memory.total_bytes)}`} />
          <p className={`text-xs leading-relaxed ${c.label}`}>
            Available RAM includes reusable cache and estimates what Linux can use without swapping.
            On Docker Desktop, these figures describe the Linux VM.
          </p>
        </>
      ) : <p className={`text-xs ${c.label}`}>RAM information unavailable.</p>}
    </div>
  );
}

function ContainerHealth({ c }) {
  const { data, error } = usePolling("worker-health", minute);
  return (
    <section className={`rt-panel rt-worker-panel rounded-xl ${c.card} ${c.title}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <PanelHeading Icon={Activity}>Container health</PanelHeading>
        {data && <p className={`text-xs ${c.label}`}>Last checked {date(data.checked_at)}</p>}
      </div>
      <Feedback c={c} error={error} />
      {!data && !error && <p className={`text-sm ${c.label}`}>Checking services…</p>}
      {data && !error && (
        <div className="overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className={c.tableHead}><tr>
              <th scope="col" className="px-2 py-2">Service</th>
              <th scope="col" className="px-2 py-2">Status</th>
              <th scope="col" className="px-2 py-2">Check</th>
            </tr></thead>
            <tbody>{data.services.map(({ service, status, check }) => (
              <tr key={service} className={c.tableRow}>
                <th scope="row" className="px-2 py-2 font-mono">{service}</th>
                <td className="px-2 py-2 capitalize">
                  <span className={`rt-status ${status === "healthy" ? states.ready[1] : states.starting[1]}`}>
                    {status}
                  </span>
                </td>
                <td className="px-2 py-2">{check}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {data && !error && <HostResources c={c} host={data.host} />}
    </section>
  );
}

const chart = { left: 62, right: 510, top: 18, bottom: 178 };
const periods = [["24h", "24 hours"], ["3d", "3 days"], ["7d", "7 days"]];
const dayTick = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const timeTick = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

const chartModes = {
  players: { title: "Players online", axis: "Players", series: [["Players", "var(--accent)"]] },
  ram: { title: "RAM usage and available", axis: "GiB", series: [["Used", "var(--accent)"], ["Available", "var(--success)"]] },
  uptime: { title: "Game server uptime", axis: "Hours", series: [["Uptime", "var(--accent)"]] },
};

function historyChart(data, mode, player) {
  if (!data) return null;
  const start = Date.parse(data.start);
  const end = Date.parse(data.end);
  const samples = mode === "players" ? data.samples : data.resources || [];
  const values = (sample) => {
    if (mode === "players") return [player ? Number(sample.online_players.includes(player)) : sample.player_count];
    if (mode === "ram") return [sample.ram_used_bytes, sample.ram_available_bytes].map((v) => v == null ? null : v / 2 ** 30);
    return [sample.game_uptime_seconds == null ? null : sample.game_uptime_seconds / 3600];
  };
  const points = samples.map((sample) => ({ at: Date.parse(sample.sampled_at), boot: sample.game_boot_id, values: values(sample) }));
  if (!points.some((point) => point.values.some((value) => value != null))) return null;
  const peak = points.reduce((max, point) => Math.max(max, ...point.values), 0);
  const step = mode === "players" ? Math.max(1, Math.ceil(peak / 4)) : Math.max(0.25, Math.ceil(peak) / 4);
  const top = Math.min(4, Math.max(1, Math.ceil(peak / step))) * step;
  const x = (time) => chart.left + (time - start) / (end - start) * (chart.right - chart.left);
  const y = (value) => chart.bottom - value / top * (chart.bottom - chart.top);
  const series = chartModes[mode].series.map(([label, color], index) => {
    let last = null;
    let line = "";
    for (const point of points) {
      const value = point.values[index];
      if (value == null) { last = null; continue; }
      const linked = last && point.at - last.at <= 120000 && (mode !== "uptime" || last.boot === point.boot);
      line += `${linked ? "L" : "M"}${x(point.at)},${y(value)}${linked ? "" : "h0.1"}`;
      last = point;
    }
    return { label, color, line };
  });
  return { x, y, series, steps: Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step),
    ticks: Array.from({ length: 4 }, (_, i) => start + (end - start) * i / 3), latest: points.at(-1) };
}

function OnlineHistory({ c }) {
  const [mode, setMode] = useState("players");
  const [period, setPeriod] = useState("24h");
  const [player, setPlayer] = useState("");
  const { data, error } = usePolling(`online-history?period=${period}`, minute);
  const names = useMemo(() => [...new Set(data?.samples.flatMap((sample) => sample.online_players) || [])].sort(), [data]);
  const filter = names.includes(player) ? player : "";
  const model = useMemo(() => historyChart(data, mode, filter), [data, mode, filter]);
  const details = chartModes[mode];
  return (
    <section className={`rt-panel rt-worker-panel rounded-xl ${c.card} ${c.title}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelHeading Icon={Users}>{details.title}</PanelHeading>
        <select aria-label="Chart type" value={mode} onChange={(event) => setMode(event.target.value)}
          className={`max-w-full rounded-md px-2 text-xs ${c.input}`}>
          <option value="players">Players online</option>
          <option value="ram">RAM usage and available</option>
          <option value="uptime">Game server uptime</option>
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="History period" className="flex flex-wrap gap-2">
          {periods.map(([id, label]) => (
            <button type="button" key={id} aria-pressed={period === id} onClick={() => setPeriod(id)}
              className={`rounded-md border px-2 text-xs font-semibold ${period === id ? c.navActive : c.btnGhost}`}>
              {label}
            </button>
          ))}
        </div>
        {mode === "players" && names.length > 0 && (
          <select aria-label="Filter history by player" value={filter} onChange={(event) => setPlayer(event.target.value)}
            className={`max-w-full rounded-md px-2 text-xs ${c.input}`}>
            <option value="">All players</option>
            {names.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        )}
      </div>
      <Feedback c={c} error={error} />
      {model ? (
        <>
          <svg className="rt-history-chart" viewBox="0 0 532 220" role="img"
            aria-label={`${details.title} over time. Time is horizontal and ${details.axis.toLowerCase()} is vertical.`}>
            <g fill="currentColor" fontSize="12">
              <text x={8} y={12}>{details.axis}</text>
              {model.steps.map((value) => (
                <g key={value}>
                  <line x1={chart.left} x2={chart.right} y1={model.y(value)} y2={model.y(value)} stroke="currentColor" opacity=".18" />
                  <text x={chart.left - 8} y={model.y(value) + 4} textAnchor="end">{value.toLocaleString()}</text>
                </g>
              ))}
              {model.ticks.map((tick, index) => (
                <g key={tick}>
                  <line x1={model.x(tick)} x2={model.x(tick)} y1={chart.top} y2={chart.bottom} stroke="currentColor" opacity=".12" />
                  <text x={model.x(tick)} y={195} textAnchor={index === 3 ? "end" : "middle"}>
                    {dayTick.format(tick)}
                    <tspan x={model.x(tick)} dy={14}>{timeTick.format(tick)}</tspan>
                  </text>
                </g>
              ))}
            </g>
            {model.series.map(({label, color, line}, index) => (
              <path key={label} d={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round"
                strokeDasharray={index ? "5 4" : undefined} />
            ))}
          </svg>
          <p className={`flex flex-wrap gap-x-4 gap-y-1 text-xs ${c.label}`}>
            <span>{date(model.latest.at)}</span>
            {model.series.map(({label, color}, index) => (
              <span key={label} className="rt-chart-legend" style={{ "--series": color, "--line-style": index ? "dashed" : "solid" }}>
                {filter || label} {model.latest.values[index] == null ? "—"
                  : `${model.latest.values[index].toLocaleString(undefined, { maximumFractionDigits: 2 })}${mode === "ram" ? " GiB" : mode === "uptime" ? " h" : ""}`}
              </span>
            ))}
          </p>
        </>
      ) : <p className={`text-sm ${c.label}`}>{data ? "No samples in this period yet." : "Loading history…"}</p>}
    </section>
  );
}

export function WorkerDashboard({ c }) {
  return (
    <div className="rt-worker rt-worker-dashboard">
      <ContainerHealth c={c} />
      <OnlineHistory c={c} />
      <ServerLogs c={c} />
    </div>
  );
}
