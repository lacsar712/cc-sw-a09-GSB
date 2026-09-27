<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const prefixes = ref([])
const events = ref([])
const rejections = ref([])
const newPrefix = ref('')
const err = ref('')
const ok = ref('')
let timer

const todayRejections = computed(() => {
  const today = new Date().toDateString()
  return rejections.value.filter((r) => new Date(r.created_at).toDateString() === today)
})

function fmtTime(iso) {
  return new Date(iso).toLocaleString()
}

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [p, e, r] = await Promise.all([
      api('/api/prefixes'),
      api('/api/prefix-events'),
      api('/api/rejections'),
    ])
    prefixes.value = p
    events.value = e
    rejections.value = r
  } catch (e2) {
    err.value = String(e2.message || e2)
  }
}

async function add() {
  err.value = ''
  ok.value = ''
  try {
    await api('/api/prefixes', { method: 'POST', body: JSON.stringify({ prefix: newPrefix.value }) })
    ok.value = `已收录前缀「${newPrefix.value.trim()}」`
    newPrefix.value = ''
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function remove(p) {
  err.value = ''
  ok.value = ''
  try {
    await api(`/api/prefixes/${p.id}`, { method: 'DELETE' })
    ok.value = `已删除前缀「${p.prefix}」，旧称呼保持原样`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2>前缀簿维护区</h2>
    <p class="hint">称呼须以簿中任一合法前缀开头，否则拒收；删前缀不改写已入队称呼。</p>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <p v-if="ok" style="color:#1a7f37">{{ ok }}</p>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>当前前缀簿</h3>
      <div v-if="role === 'writer'" style="margin-bottom:10px;">
        <input v-model="newPrefix" placeholder="新前缀，如：氖" @keyup.enter="add" />
        <button type="button" @click="add">收录前缀</button>
      </div>
      <p v-else class="hint">巡检员只读，不可增删前缀。</p>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr><th>编号</th><th>前缀</th><th>收录人</th><th>收录时间</th><th v-if="role === 'writer'">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="p in prefixes" :key="p.id">
            <td>{{ p.id }}</td>
            <td>{{ p.prefix }}</td>
            <td>{{ p.created_by }}</td>
            <td>{{ fmtTime(p.created_at) }}</td>
            <td v-if="role === 'writer'"><button type="button" @click="remove(p)">删除</button></td>
          </tr>
          <tr v-if="!prefixes.length"><td :colspan="role === 'writer' ? 5 : 4">簿为空，任何称呼都将被拒收</td></tr>
        </tbody>
      </table>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>当日拒收样例</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr><th>编号</th><th>被拒称呼</th><th>拒收理由</th><th>提交人</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in todayRejections" :key="r.id">
            <td>{{ r.id }}</td>
            <td>{{ r.lamp }}</td>
            <td>{{ r.reason }}</td>
            <td>{{ r.created_by }}</td>
            <td>{{ fmtTime(r.created_at) }}</td>
          </tr>
          <tr v-if="!todayRejections.length"><td colspan="5">当日暂无拒收</td></tr>
        </tbody>
      </table>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>变更履历</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr><th>编号</th><th>动作</th><th>前缀</th><th>操作人</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td>{{ e.id }}</td>
            <td>{{ e.action === 'add' ? '收录' : '删除' }}</td>
            <td>{{ e.prefix }}</td>
            <td>{{ e.actor }}</td>
            <td>{{ fmtTime(e.created_at) }}</td>
          </tr>
          <tr v-if="!events.length"><td colspan="5">暂无变更</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.hint {
  color: #666;
  font-size: 13px;
}
</style>
