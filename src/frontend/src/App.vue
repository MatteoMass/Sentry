<script setup lang="ts">
/** The two panes: the tree on the left, the selected recording in the middle. */
import { onMounted } from "vue";

import FolderTree from "@/components/FolderTree.vue";
import RecordingDetail from "@/components/RecordingDetail.vue";
import { useLibrary } from "@/composables/useLibrary";

const { refresh } = useLibrary();

onMounted(refresh);
</script>

<template>
  <div class="layout">
    <FolderTree />
    <RecordingDetail />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100%;
}
</style>
