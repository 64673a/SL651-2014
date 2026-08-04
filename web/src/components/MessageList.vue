<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { formatAnyToDisplay } from "../datetime";

const props = defineProps({
  messages: { type: Array, default: () => [] },
  direction: { type: String, default: "all" },
  peer: { type: String, default: "" },
  /** 新消息到达时自动滚到顶部（最新在上方） */
  autoScroll: { type: Boolean, default: false },
});
const emit = defineEmits(["select"]);
const listEl = ref(null);

/** 统一按时间倒序：最新在上方 */
const filtered = computed(() => {
  let list = props.messages || [];
  if (props.direction && props.direction !== "all") {
    list = list.filter((m) => m.direction === props.direction);
  }
  const ip = (props.peer || "").trim().toLowerCase();
  if (ip) {
    list = list.filter((m) => (m.peer || "").toLowerCase().includes(ip));
  }
  return [...list].sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));
});

/** 监听条目数变化：autoScroll 时滚回顶部看最新 */
watch(
  () => filtered.value.length,
  async () => {
    if (!props.autoScroll) return;
    await nextTick();
    if (listEl.value) listEl.value.scrollTop = 0;
  }
);

function dirColor(d) {
  if (d === "up") return "success";
  if (d === "down") return "info";
  return "warning";
}

function summary(m) {
  const p = m.parsed || {};
  const b = p.body || {};
  const parts = [];
  if (m.func_name || m.func_code) parts.push(`${m.func_code || ""} ${m.func_name || ""}`.trim());
  if (b.send_time || m.send_time) {
    parts.push(`发报 ${formatAnyToDisplay(b.send_time || m.send_time)}`);
  }
  if (b.serial_no != null || m.serial_no != null) parts.push(`流水号 ${b.serial_no ?? m.serial_no}`);
  if (b.elements?.length) {
    b.elements.slice(0, 3).forEach((e) => {
      const v = e.value != null ? e.value : e.value_text || e.raw;
      parts.push(`${e.name}: ${v}`);
    });
  }
  return parts;
}

function crcOk(m) {
  if (m.crc_ok === true || m.crc_ok === false) return m.crc_ok;
  if (m.parsed?.crc_ok === true || m.parsed?.crc_ok === false) return m.parsed.crc_ok;
  return null;
}

function stationAddr(m) {
  return (
    m.remote_addr ||
    m.parsed?.header?.remote_addr ||
    m.parsed?.body?.remote_addr ||
    ""
  );
}
</script>

<template>
  <div ref="listEl" class="h-full min-h-0 overflow-y-auto overscroll-contain space-y-2 p-3">
    <UEmpty
      v-if="!filtered.length"
      icon="i-lucide-inbox"
      title="暂无报文"
      description="等待 RTU 上报，或启动模拟 RTU"
    />

    <div
      v-for="m in filtered"
      :key="m.id"
      role="button"
      tabindex="0"
      class="block w-full shrink-0 cursor-pointer rounded-xl border border-default bg-elevated/40 p-4 transition hover:bg-elevated"
      @click="emit('select', m)"
      @keydown.enter="emit('select', m)"
    >
      <div class="flex flex-wrap items-center gap-2 mb-2">
        <UBadge :color="dirColor(m.direction)" variant="subtle" size="sm">
          {{ (m.direction || "?").toUpperCase() }}
        </UBadge>
        <span class="text-xs text-muted font-mono">{{ formatAnyToDisplay(m.ts) }}</span>
        <span class="text-xs font-mono text-highlighted">{{ stationAddr(m) || "—" }}</span>
        <span v-if="m.peer" class="text-[11px] text-dimmed font-mono">{{ m.peer }}</span>
        <span class="text-sm font-medium">{{ m.func_name || m.note || "" }}</span>
        <UBadge
          v-if="crcOk(m) !== null"
          :color="crcOk(m) ? 'success' : 'error'"
          variant="subtle"
          size="sm"
          :label="crcOk(m) ? 'CRC✓' : 'CRC✗'"
        />
      </div>

      <p v-if="m.raw_hex" class="font-mono text-xs text-toned break-all leading-relaxed">
        {{ m.raw_hex }}
      </p>
      <p v-else class="text-xs text-muted">{{ m.note || "—" }}</p>

      <div v-if="summary(m).length" class="mt-2 flex flex-wrap gap-1.5">
        <UBadge v-for="(s, i) in summary(m)" :key="i" color="neutral" variant="soft" size="sm">
          {{ s }}
        </UBadge>
      </div>

      <UAlert
        v-if="m.error || (m.parsed?.errors || []).length"
        class="mt-2"
        color="error"
        variant="subtle"
        icon="i-lucide-triangle-alert"
        :title="m.error || (m.parsed.errors || []).join('; ')"
      />
    </div>
  </div>
</template>
