<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api.js'

const router = useRouter()
const role = ref(localStorage.getItem('role') || '')
const jobs = ref([])
const prefixes = ref([])
const err = ref('')
const form = ref({ lamp: '', nominal_nm: 0.15, measured_nm: 0.15 })
let timer

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [jobList, p] = await Promise.all([api('/api/jobs'), api('/api/prefixes')])
    jobs.value = jobList
    prefixes.value = p.prefixes || []
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function submit() {
  err.value = ''
  try {
    await api('/api/jobs', { method: 'POST', body: JSON.stringify(form.value) })
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function goDetail(id) {
  router.push(`/jobs/${id}`)
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
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <section v-if="role === 'writer'" style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>提交校准</h3>
      <p class="prefix-hint">
        合法前缀：
        <template v-if="prefixes.length">
          <b v-for="(p, i) in prefixes" :key="p">{{ i ? '、' : '' }}{{ p }}</b>
        </template>
        <b v-else>（前缀簿为空，任何称呼都会被拒收）</b>
        ；称呼必须以任一前缀开头，否则拒收（见
        <router-link to="/prefixes">前缀簿</router-link>）。
      </p>
      <label>灯种 <input v-model="form.lamp" /></label>
      <label>标称 nm <input type="number" step="0.01" v-model.number="form.nominal_nm" /></label>
      <label>实测 nm <input type="number" step="0.01" v-model.number="form.measured_nm" /></label>
      <button @click="submit">入队</button>
    </section>
    <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
      <thead>
        <tr>
          <th>编号</th><th>灯种</th><th>标称</th><th>实测</th><th>状态</th><th>结论</th><th>理由</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="j in jobs"
          :key="j.id"
          style="cursor:pointer"
          @click="goDetail(j.id)"
        >
          <td>{{ j.id }}</td>
          <td>{{ j.lamp }}</td>
          <td>{{ j.nominal_nm }}</td>
          <td>{{ j.measured_nm }}</td>
          <td>{{ j.status }}</td>
          <td>{{ j.verdict }}</td>
          <td>{{ j.reason }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.prefix-hint {
  font-size: 13px;
  color: #555;
}
</style>
