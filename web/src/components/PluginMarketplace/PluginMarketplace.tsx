'use client';
import { useState, useEffect, useCallback } from 'react';
import { API_URL } from '@/constants/api';

interface Plugin {
  plugin_id: string;
  name: string;
  description: string;
  author: string;
  installed: boolean;
  install_count: number;
}

export function PluginMarketplace() {
  const [plugins, setPlugins]   = useState<Plugin[]>([]);
  const [loading, setLoading]   = useState(true);
  const [acting, setActing]     = useState<string | null>(null);

  const fetchPlugins = useCallback(() => {
    setLoading(true);
    fetch(`${API_URL}/plugins`)
      .then((r) => r.json())
      .then((d) => setPlugins(d.plugins ?? []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchPlugins(); }, [fetchPlugins]);

  const install = useCallback(async (plugin: Plugin) => {
    setActing(plugin.name);
    try {
      await fetch(`${API_URL}/plugins/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: plugin.name,
          description: plugin.description,
          tool_definition: {},
          author: plugin.author,
        }),
      });
      setPlugins((prev) => prev.map((p) => p.name === plugin.name ? { ...p, installed: true, install_count: p.install_count + 1 } : p));
    } catch { /* ignore */ }
    setActing(null);
  }, []);

  const uninstall = useCallback(async (name: string) => {
    setActing(name);
    try {
      await fetch(`${API_URL}/plugins/${encodeURIComponent(name)}`, { method: 'DELETE' });
      setPlugins((prev) => prev.map((p) => p.name === name ? { ...p, installed: false } : p));
    } catch { /* ignore */ }
    setActing(null);
  }, []);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-faint text-sm">
        Loading plugins…
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto">
        <h2 className="text-base font-semibold text-text-primary mb-1">Plugin Marketplace</h2>
        <p className="text-xs text-text-faint mb-5">
          Install community plugins to extend agent capabilities.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {plugins.map((p) => (
            <div key={p.name}
              className={`bg-surface-card border rounded-xl p-4 flex flex-col gap-2 transition-colors
                ${p.installed ? 'border-accent-blue/40' : 'border-border-dim'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <span className="text-sm font-medium text-text-primary font-mono">{p.name}</span>
                  {p.installed && (
                    <span className="ml-2 text-[10px] bg-blue-950 text-accent-blue rounded px-1.5 py-0.5">installed</span>
                  )}
                </div>
                <span className="text-[10px] text-text-ghost flex-shrink-0">{p.install_count} installs</span>
              </div>

              <p className="text-xs text-text-secondary leading-relaxed">{p.description}</p>

              <div className="flex items-center justify-between mt-auto pt-1">
                <span className="text-[10px] text-text-ghost">by {p.author}</span>
                {p.installed ? (
                  <button
                    onClick={() => uninstall(p.name)}
                    disabled={acting === p.name}
                    className="text-[11px] border border-border-strong rounded-lg px-2.5 py-1 text-text-faint hover:text-red-400 hover:border-red-900 transition-colors disabled:opacity-50"
                  >
                    {acting === p.name ? 'Removing…' : 'Uninstall'}
                  </button>
                ) : (
                  <button
                    onClick={() => install(p)}
                    disabled={acting === p.name}
                    className="text-[11px] bg-accent-blue text-white rounded-lg px-2.5 py-1 hover:bg-blue-500 transition-colors disabled:opacity-50"
                  >
                    {acting === p.name ? 'Installing…' : 'Install'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {plugins.length === 0 && (
          <div className="text-center text-text-faint py-12 text-sm">No plugins available.</div>
        )}
      </div>
    </div>
  );
}
