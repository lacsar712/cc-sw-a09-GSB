<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const prefixes = ref([])
const audit = ref([])
const rejected = ref([])
const newPrefix = ref('')
const err = ref('')
let timer

const canEdit = computed(() => role.value === 'writer')

const ACTION_LABEL = { seed: '初始', add: '新增', remove: '删除' }

function actionText(a) {
  return ACTION_LABEL[a] || a
}

function fmtTime(t) {
  if (!t) return ''
  return t.replace('T', ' ').replace(/\.\d+.*$/, '')
}

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [p, a, r] = await Promise.all([
      api('/api/prefixes'),
      api('/api/prefixes/audit'),
      api('/api/rejected'),
    ])
    prefixes.value = p.prefixes || []
    audit.value = a || []
    rejected.value = r || []
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function addPrefix() {
  err.value = ''
  const v = newPrefix.value.trim()
  if (!v) {
    err.value = '前缀不能为空'
    return
  }
  try {
    await api('/api/prefixes', { method: 'POST', body: JSON.stringify({ prefix: v }) })
    newPrefix.value = ''
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function removePrefix(p) {
  err.value = ''
  if (!window.confirm(`确认删除前缀「${p}」？旧单称呼不会被改写，之后以该前缀开头的称呼将被拒收。`)) return
  try {
    await api('/api/prefixes/delete', { method: 'POST', body: JSON.stringify({ prefix: p }) })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2>灯种前缀簿</h2>
    <p class="hint">称呼必须以簿中任一合法前缀<b>开头</b>，否则提交即拒收。前缀增删写入变更履历；删除前缀不影响已入队旧单的原称呼。</p>
    <p v-if="err" style="color:#b00020">{{ err }}</p>

    <section class="card">
      <h3>合法前缀</h3>
      <div v-if="prefixes.length" class="prefix-list">
        <span v-for="p in prefixes" :key="p" class="prefix-chip">
          {{ p }}
          <button
            v-if="canEdit"
            type="button"
            class="chip-del"
            title="删除该前缀"
            @click="removePrefix(p)"
          >×</button>
        </span>
      </div>
      <p v-else class="hint">前缀簿为空：此时任何称呼都会被拒收。</p>
      <div v-if="canEdit" class="add-row">
        <input v-model="newPrefix" placeholder="新增前缀，如：氦" @keyup.enter="addPrefix" />
        <button type="button" @click="addPrefix">新增前缀</button>
      </div>
      <p v-else class="hint">巡检员为只读权限，可查看前缀簿与履历，不可增删。</p>
    </section>

    <section class="card">
      <h3>当日拒收样例</h3>
      <table v-if="rejected.length" border="1" cellpadding="6" class="grid">
        <thead>
          <tr><th>编号</th><th>称呼</th><th>标称</th><th>实测</th><th>拒收原因</th><th>提交人</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in rejected" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.lamp }}</td>
            <td>{{ r.nominal_nm }}</td>
            <td>{{ r.measured_nm }}</td>
            <td>{{ r.reason }}</td>
            <td>{{ r.created_by }}</td>
            <td>{{ fmtTime(r.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="hint">今日暂无拒收记录。</p>
    </section>

    <section class="card">
      <h3>变更履历</h3>
      <table v-if="audit.length" border="1" cellpadding="6" class="grid">
        <thead>
          <tr><th>编号</th><th>操作</th><th>前缀</th><th>操作人</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in audit" :key="a.id">
            <td>{{ a.id }}</td>
            <td>{{ actionText(a.action) }}</td>
            <td>{{ a.prefix }}</td>
            <td>{{ a.changed_by }}</td>
            <td>{{ fmtTime(a.changed_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="hint">暂无变更记录。</p>
    </section>
  </div>
</template>

<style scoped>
.hint {
  color: #555;
  font-size: 13px;
}
.card {
  margin: 16px 0;
  padding: 12px;
  border: 1px solid #ccc;
}
.prefix-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.prefix-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 14px;
  background: #e8f0fe;
  border: 1px solid #b8cdf0;
  font-size: 14px;
}
.chip-del {
  border: none;
  background: transparent;
  color: #b00020;
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  padding: 0 2px;
}
.add-row {
  display: flex;
  gap: 8px;
}
.add-row input {
  padding: 4px 8px;
}
.grid {
  border-collapse: collapse;
  width: 100%;
}
</style>
