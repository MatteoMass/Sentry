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
/* The tree is drawn over the recording, not beside it, on a window too narrow
   to hold both — so it is positioned against this. */
.layout {
  position: relative;
  display: flex;
  height: 100%;
}
</style>
