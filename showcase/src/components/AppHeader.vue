<script setup lang="ts">
import { NAV } from '../data/business';

const year = new Date().getFullYear();
</script>

<template>
  <header class="app-header">
    <div class="container">
      <a href="#" class="brand">ERP Lite · Showcase</a>
      <nav aria-label="primary">
        <a v-for="n in NAV" :key="n.href" :href="n.href">{{ n.label }}</a>
      </nav>
    </div>
  </header>
</template>

<script lang="ts">
export default { name: 'AppHeader' };
</script>