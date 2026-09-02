<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()
</script>

<template>
  <div class="err-page">
    <el-result icon="warning" title="403" sub-title="无权限访问该页面（当前账号缺少所需权限点）">
      <template #extra>
        <el-button type="primary" @click="router.replace('/dashboard')">返回首页</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.err-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f5f8;
}
</style>
