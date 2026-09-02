<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { ApiBusinessError } from '@/api/request'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// 演示账号卡片（不自动填充密码，仅提示）
const demoAccounts = [
  { username: 'admin', password: 'admin123', role: '系统管理员' },
  { username: 'zhangsan', password: 'demo123', role: '研发申请人（APPLICANT）' },
  { username: 'lisi', password: 'demo123', role: '研发部门主管（DEPT_MANAGER）' },
  { username: 'wangwu', password: 'demo123', role: '采购员（BUYER）' },
  { username: 'zhaoliu', password: 'demo123', role: '仓库管理员（WAREHOUSE）' },
]

async function onLogin() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.replace(redirect)
  } catch (err) {
    // 错误 toast 已由 request client 统一处理
    if (err instanceof ApiBusinessError && err.code === 0) {
      /* noop */
    }
  } finally {
    loading.value = false
  }
}

function fillDemo(u: string) {
  // 只填用户名，密码保持手动输入（规范：不要自动填写密码）
  form.username = u
  formRef.value?.clearValidate()
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-head">
        <div class="logo">E</div>
        <h1>制造企业采购库存协同系统</h1>
        <p>Manufacturing ERP Lite · Phase 10 Frontend</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onLogin">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" clearable />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onLogin">
          登 录
        </el-button>
      </el-form>

      <el-divider content-position="left"><span class="demo-divider">演示账号</span></el-divider>
      <div class="demo-list">
        <div v-for="acc in demoAccounts" :key="acc.username" class="demo-row" @click="fillDemo(acc.username)">
          <el-tag size="small" effect="plain">{{ acc.username }}</el-tag>
          <span class="demo-role">{{ acc.role }}</span>
          <span class="demo-pwd">密码 {{ acc.password }}</span>
        </div>
        <p class="demo-tip">点击账号自动填入用户名（密码需手动输入）。真实演示通过退出 → 换账号登录体现 RBAC。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #eef2fb 0%, #f6f8fc 45%, #e9eef7 100%);
}
.login-card {
  width: 420px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(31, 35, 41, 0.1);
  padding: 32px 36px 24px;
}
.login-head {
  text-align: center;
  margin-bottom: 22px;
}
.logo {
  width: 48px;
  height: 48px;
  margin: 0 auto 12px;
  border-radius: 10px;
  background: #2f6fed;
  color: #fff;
  font-size: 26px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.login-head h1 {
  font-size: 19px;
  margin: 0 0 6px;
  color: #1f2329;
}
.login-head p {
  margin: 0;
  font-size: 12px;
  color: #8a919f;
}
.login-btn {
  width: 100%;
}
.demo-divider {
  font-size: 12px;
  color: #8a919f;
}
.demo-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.demo-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}
.demo-row:hover {
  background: #f4f7ff;
  border-color: #d6e2ff;
}
.demo-role {
  flex: 1;
  font-size: 12px;
  color: #4b5563;
}
.demo-pwd {
  font-size: 11px;
  color: #b0b7c3;
  font-family: ui-monospace, monospace;
}
.demo-tip {
  margin: 8px 0 0;
  font-size: 11px;
  color: #b0b7c3;
  line-height: 1.5;
}
</style>
