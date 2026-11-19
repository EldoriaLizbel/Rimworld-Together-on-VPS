"use client";

import { useState } from "react";
import { Database, RefreshCw } from "lucide-react";
import { usePolling } from "./GamePage";

function Cell({ value }) {
  if (value == null) return <span>—</span>;
  if (typeof value === "object") return <details>
    <summary className="cursor-pointer text-[color:var(--accent)]">{Array.isArray(value) ? `${value.length} items` : "View JSON"}</summary>
    <pre tabIndex={0} className="mt-2 max-h-64 max-w-lg overflow-auto p-2 text-xs">{JSON.stringify(value, null, 2)}</pre>
  </details>;
  return <span className="break-words">{String(value)}</span>;
}

export default function ServerData({ c }) {
  const [selected, setSelected] = useState("world_config");
  const [page, setPage] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const catalog = usePolling("data-tables", 60000);
  const records = usePolling(`data-rows?table=${selected}&page=${page}`, 60000, refresh);
  const error = catalog.error || records.error;
  return <div className="grid min-w-0 gap-4">
    <section className={`rt-panel rounded-xl p-4 ${c.card} ${c.title}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Database size={18} aria-hidden="true" />Server data</h2>
          <p className={`mt-1 text-xs ${c.label}`}>Read-only · 50 rows per page · updates every minute</p>
        </div>
        <button type="button" className="rt-button" onClick={() => setRefresh((n) => n + 1)}>
          <RefreshCw size={16} aria-hidden="true" />Refresh
        </button>
      </div>
      <nav className="mt-4 flex flex-wrap gap-2" aria-label="Server tables">
        {(catalog.data?.tables || []).map((table) => <button key={table.name} type="button" className={table.name === selected ? "rt-button bg-[var(--accent-bg)] text-[color:var(--accent)]" : "rt-button"}
          aria-pressed={table.name === selected} onClick={() => { setSelected(table.name); setPage(0); }}>{table.label}</button>)}
      </nav>
    </section>
    <section className={`rt-panel min-w-0 rounded-xl p-4 ${c.card} ${c.title}`} aria-busy={!records.data && !error}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-mono text-sm font-semibold">{selected}</h2>
        <span className={`text-xs ${c.label}`}>{records.checkedAt ? `Checked ${records.checkedAt.toLocaleTimeString()}` : ""}</span>
      </div>
      {error && <p role="alert" className={c.error}>{error}</p>}
      {!records.data ? (!error && <p role="status">Loading records…</p>) : !records.data.rows.length ?
        <p role="status" className={`py-6 text-sm ${c.label}`}>No records in this table yet.</p> :
        <div className="max-h-[65vh] overflow-auto rounded-lg border border-[color:var(--border)]" tabIndex={0} role="region" aria-label={`${selected} records`}>
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{selected}, page {page + 1}</caption>
            <thead className="sticky top-0 bg-[color:var(--surface)]"><tr>
              {records.data.columns.map((column) => <th key={column} scope="col" className="whitespace-nowrap px-3 py-3">{column}</th>)}
            </tr></thead>
            <tbody>{records.data.rows.map((row, index) => <tr key={index} className="border-t border-[color:var(--border)]">
              {records.data.columns.map((column) => <td key={column} className="min-w-32 max-w-lg px-3 py-3 align-top"><Cell value={row[column]} /></td>)}
            </tr>)}</tbody>
          </table>
        </div>}
      <div className="mt-4 flex items-center justify-between gap-3">
        <span className={`text-xs ${c.label}`}>Page {page + 1}</span>
        <div className="flex gap-2">
          <button type="button" className="rt-button" disabled={page === 0 || !records.data} onClick={() => setPage((n) => n - 1)}>Previous</button>
          <button type="button" className="rt-button" disabled={!records.data?.has_more} onClick={() => setPage((n) => n + 1)}>Next</button>
        </div>
      </div>
    </section>
  </div>;
}
