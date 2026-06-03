import { useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Plus, Trash2, Save, RotateCcw, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { api } from '@/lib/api'

/**
 * Settings — V2 #5: GET + PATCH /api/config.
 *
 * The /api/config endpoint is intentionally schema-less: a generic
 * key-value JSON object (per V2 #3 design). We render it as an
 * editable list of (key, value) rows. Add / remove rows, then
 * "保存" sends PATCH /api/config with the full object.
 *
 * The V1 read-only mock cards (openclaw / ASR / TTS) are kept as
 * informational cards above the editor — they describe the actual
 * server-side wiring that PATCH /api/config does NOT touch
 * (those live in config/config.yaml + env vars).
 */
export function Settings() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null)
  const [draft, setDraft] = useState<Array<[string, string]>>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getConfig()
      setConfig(data)
      setDraft(Object.entries(data).map(([k, v]) => [k, JSON.stringify(v)]))
      setDirty(false)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function updateRow(i: number, key: string, value: string) {
    setDraft((d) => {
      const next = [...d]
      next[i] = [key, value]
      return next
    })
    setDirty(true)
  }

  function addRow() {
    setDraft((d) => [...d, ['', '']])
    setDirty(true)
  }

  function removeRow(i: number) {
    setDraft((d) => d.filter((_, idx) => idx !== i))
    setDirty(true)
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const payload: Record<string, unknown> = {}
      for (const [k, v] of draft) {
        if (!k.trim()) continue
        // Try to parse JSON-ish values; fall back to raw string.
        // That way users can type "42" → 42 (number) and "true" → true.
        if (v === 'true') payload[k] = true
        else if (v === 'false') payload[k] = false
        else if (v === 'null') payload[k] = null
        else if (/^-?\d+$/.test(v)) payload[k] = Number(v)
        else if (/^-?\d+\.\d+$/.test(v)) payload[k] = Number(v)
        else payload[k] = v
      }
      const updated = await api.updateConfig(payload)
      setConfig(updated)
      setDraft(Object.entries(updated).map(([k, v]) => [k, JSON.stringify(v)]))
      setDirty(false)
      toast.success('设置已保存')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      toast.error(`保存失败：${msg}`)
    } finally {
      setSaving(false)
    }
  }

  function reset() {
    if (config) {
      setDraft(Object.entries(config).map(([k, v]) => [k, JSON.stringify(v)]))
      setDirty(false)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-xl font-semibold">设置</h2>
        <p className="text-sm text-muted-foreground">
          运行时配置（PATCH /api/config）。
          <span className="ml-1 text-amber-500">
            以下是 *运行时* 配置；服务自身连接信息在 config/config.yaml + 环境变量，不在这里改。
          </span>
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>OpenClaw</CardTitle>
          <CardDescription>LLM/agent 运行时（宿主机上的 openclaw gateway）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Base URL</Label>
            <Input defaultValue="http://host.docker.internal:18789" readOnly />
          </div>
          <div className="space-y-1.5">
            <Label>模型（agent target）</Label>
            <Input defaultValue="openclaw" readOnly />
            <p className="text-xs text-muted-foreground">
              固定为 "openclaw"；后端 LLM 由 openclaw 端 agents.defaults 决定。
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>ASR</CardTitle>
          <CardDescription>语音识别服务（V1 仅 mock）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Provider</Label>
            <Input defaultValue="mock" readOnly />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>TTS</CardTitle>
          <CardDescription>语音合成服务（V1 仅 mock）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1.5">
            <Label>Provider</Label>
            <Input defaultValue="mock" readOnly />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>运行时配置（K-V）</CardTitle>
          <CardDescription>
            任意 JSON 兼容的 key/value 对，PATCH /api/config 全量覆盖写入。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
            </div>
          )}
          {error && (
            <p className="text-sm text-destructive">加载失败：{error}</p>
          )}
          {!loading && !error && (
            <>
              {draft.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  还没有配置项。点下方 “新增行” 加一个。
                </p>
              ) : (
                <div className="space-y-2">
                  {draft.map(([k, v], i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Input
                        value={k}
                        onChange={(e) => updateRow(i, e.target.value, v)}
                        placeholder="key"
                        className="font-mono text-xs"
                      />
                      <Input
                        value={v}
                        onChange={(e) => updateRow(i, k, e.target.value)}
                        placeholder='value (JSON: "42", true, "str", null)'
                        className="font-mono text-xs"
                      />
                      <button
                        onClick={() => removeRow(i)}
                        className="p-2 rounded-md hover:bg-muted text-muted-foreground hover:text-destructive"
                        title="删除"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2 pt-2">
                <button
                  onClick={addRow}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-muted text-sm hover:bg-muted/70"
                >
                  <Plus className="h-4 w-4" /> 新增行
                </button>
                <button
                  onClick={save}
                  disabled={!dirty || saving}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-sm hover:opacity-90 disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Save className="h-4 w-4" />
                  )}
                  保存
                </button>
                <button
                  onClick={reset}
                  disabled={!dirty || saving}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm hover:bg-muted disabled:opacity-50"
                >
                  <RotateCcw className="h-4 w-4" /> 还原
                </button>
                {dirty && (
                  <span className="text-xs text-amber-500 ml-2">有未保存修改</span>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
