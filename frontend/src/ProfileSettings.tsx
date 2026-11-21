import { useState, type FormEvent } from 'react'

type Profile = {
  email: string
  display_name: string
}

export function ProfileSettings({ profile, onSaved, onLogout }: {
  profile: Profile
  onSaved: (profile: Profile) => void
  onLogout: () => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(profile.display_name)
  const [saving, setSaving] = useState(false)
  const [feedback, setFeedback] = useState<{ text: string; error?: boolean } | null>(null)

  function toggleSettings() {
    setOpen(!open)
    setName(profile.display_name)
    setFeedback(null)
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const displayName = name.trim()
    if (!displayName || Array.from(displayName).length > 100) {
      setFeedback({ text: '请输入 1 至 100 个字符的显示名称。', error: true })
      return
    }

    setSaving(true)
    setFeedback(null)
    try {
      const response = await fetch('/api/v1/users/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'zhiyan' },
        body: JSON.stringify({ display_name: displayName }),
      })
      if (response.status === 401) {
        setFeedback({ text: '登录已过期，请退出后重新登录。', error: true })
        return
      }
      if (!response.ok) throw new Error('保存失败')

      const updated: Profile = await response.json()
      onSaved(updated)
      setName(updated.display_name)
      setFeedback({ text: '显示名称已保存。' })
    } catch {
      setFeedback({ text: '暂时无法保存，请重试。', error: true })
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="actions profile-actions">
        <button
          type="button"
          className="secondary"
          aria-expanded={open}
          aria-controls="profile-settings"
          disabled={saving}
          onClick={toggleSettings}
        >
          {open ? '收起设置' : '个人设置'}
        </button>
        <button type="button" className="secondary" disabled={saving} onClick={onLogout}>退出登录</button>
      </div>
      <div id="profile-settings" className="profile-panel" hidden={!open}>
        {open && (
          <form onSubmit={save}>
            <p className="note">回收站项目无限期保留，自动清理尚未实现。回收站不能代替备份。</p>
            <label>
              显示名称
              <input
                required
                autoComplete="nickname"
                value={name}
                disabled={saving}
                onChange={event => {
                  setName(event.target.value)
                  setFeedback(null)
                }}
              />
            </label>
            <button type="submit" disabled={saving}>{saving ? '正在保存' : '保存显示名称'}</button>
            {feedback && <p className={feedback.error ? 'feedback' : undefined} role="status">{feedback.text}</p>}
          </form>
        )}
      </div>
    </>
  )
}
