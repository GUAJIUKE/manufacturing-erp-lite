<script setup lang="ts">
import AppHeader from './components/AppHeader.vue';
import AppFooter from './components/AppFooter.vue';

import HeroSection from './sections/HeroSection.vue';
import OverviewSection from './sections/OverviewSection.vue';
import BusinessFlowSection from './sections/BusinessFlowSection.vue';
import QuantityChainSection from './sections/QuantityChainSection.vue';
import InventoryLedgerSection from './sections/InventoryLedgerSection.vue';
import StateMachineSection from './sections/StateMachineSection.vue';
import RbacSection from './sections/RbacSection.vue';
import DashboardPreviewSection from './sections/DashboardPreviewSection.vue';
import ArchitectureSection from './sections/ArchitectureSection.vue';
import ChallengesSection from './sections/ChallengesSection.vue';
import TestingSection from './sections/TestingSection.vue';
import GallerySection from './sections/GallerySection.vue';
import DocsSection from './sections/DocsSection.vue';

import { useReveal } from './composables/useReveal';
useReveal('.reveal');
</script>

<template>
  <AppHeader />
  <main>
    <HeroSection />
    <OverviewSection />
    <BusinessFlowSection />
    <QuantityChainSection />
    <InventoryLedgerSection />
    <StateMachineSection />
    <RbacSection />
    <DashboardPreviewSection />
    <ArchitectureSection />
    <ChallengesSection />
    <TestingSection />
    <GallerySection />
    <DocsSection />
  </main>
  <AppFooter />
</template>