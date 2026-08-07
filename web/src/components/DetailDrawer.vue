<script setup>
import { computed, ref, watch } from "vue";
import { formatAnyToDisplay } from "../datetime";
import HexMap from "./HexMap.vue";
import { prettySlimMessage } from "../formatJson";
import { writeClipboard } from "../clipboard";
import { wireEncoding, wireEncodingColor, wireEncodingLabel } from "../wireEncoding";

const props = defineProps({ message: Object });
const emit = defineEmits(["close"]);

/** 本地缓存，关闭动画结束前保持内容，避免闪透明空窗 */
const localMessage = ref(null);
const open = ref(false);

/** 点击锁定的字段 */
const activeId = ref(null);
/** 悬停临时字段 */
const hoverFieldId = ref(null);
const hoverOffset = ref(null);
const showJson = ref(false);
/** ASCII 帧：原始报文(hex 字节图) / ASCII 字符文本 */
const rawMode = ref("hex");

watch(
  () => props.message,
  (msg) => {
    if (msg) {
      localMessage.value = msg;
      open.value = true;
      activeId.value = null;
      hoverFieldId.value = null;
      hoverOffset.value = null;
      showJson.value = false;
      rawMode.value = "hex";
    } else if (open.value) {
      // 父组件直接清空时：先关动画，内容保留到 after:leave
      open.value = false;
    }
  }
);

// 切换原始/ASCII 视图时上层高度变化，字段 mouseleave 可能不触发，清掉悬停高亮
watch(rawMode, () => {
  hoverFieldId.value = null;
  hoverOffset.value = null;
});

function requestClose() {
  open.value = false;
}

function onAfterLeave() {
  localMessage.value = null;
  activeId.value = null;
  hoverFieldId.value = null;
  hoverOffset.value = null;
  showJson.value = false;
  rawMode.value = "hex";
  emit("close");
}

const message = computed(() => localMessage.value);
const parsed = computed(() => message.value?.parsed || null);

const bytes = computed(() => {
  const hex = (parsed.value?.raw_hex || message.value?.raw_hex || "").replace(/\s+/g, "");
  const out = [];
  for (let i = 0; i + 1 < hex.length; i += 2) {
    out.push({ offset: i / 2, hex: hex.slice(i, i + 2).toUpperCase() });
  }
  return out;
});

const fields = computed(() => parsed.value?.fields || []);
const encoding = computed(() => (message.value ? wireEncoding(message.value) : ""));
const encodingLabel = computed(() => (message.value ? wireEncodingLabel(message.value) : "未知"));
const encodingColor = computed(() => (message.value ? wireEncodingColor(message.value) : "warning"));

const groups = computed(() => {
  const order = ["header", "body", "trailer"];
  const labels = { header: "帧头", body: "正文", trailer: "帧尾" };
  return order
    .map((g) => ({
      key: g,
      label: labels[g],
      items: fields.value.filter((f) => f.group === g),
    }))
    .filter((g) => g.items.length);
});

const highlightId = computed(() => hoverFieldId.value || activeId.value);

const fieldByOffset = computed(() => {
  const map = new Map();
  for (const f of fields.value) {
    for (let i = f.start; i < f.end; i++) {
      if (!map.has(i)) map.set(i, f);
    }
  }
  return map;
});

function onHoverByte(offset) {
  hoverOffset.value = offset;
  const f = fieldByOffset.value.get(offset);
  hoverFieldId.value = f ? f.id : null;
}

function onHexLeave() {
  hoverOffset.value = null;
  hoverFieldId.value = null;
}

function onClickField(id) {
  activeId.value = id;
}

function onFieldEnter(f) {
  hoverFieldId.value = f.id;
  hoverOffset.value = f.start;
}

function onFieldLeave() {
  hoverFieldId.value = null;
  hoverOffset.value = null;
}

function fieldHex(f) {
  return bytes.value
    .slice(f.start, f.end)
    .map((b) => b.hex)
    .join(" ");
}

/** 原始报文（连续大写 hex，便于粘贴调试） */
const rawHex = computed(() => {
  const h = parsed.value?.raw_hex || message.value?.raw_hex || "";
  return String(h).replace(/\s+/g, "").toUpperCase();
});

const rawHexSpaced = computed(() =>
  rawHex.value.replace(/(.{2})/g, "$1 ").trim()
);

const CTRL_ASCII = {
  0x01: "<SOH>",
  0x02: "<STX>",
  0x03: "<ETX>",
  0x04: "<EOT>",
  0x05: "<ENQ>",
  0x06: "<ACK>",
  0x15: "<NAK>",
  0x16: "<SYN>",
  0x17: "<ETB>",
  0x1b: "<ESC>",
};

/** 与后端 _ascii_display 一致：控制符用名称，可打印 ASCII 原样 */
const rawAsciiText = computed(() => {
  const fromParsed = String(parsed.value?.raw_text || "").trim();
  if (fromParsed) return fromParsed;
  if (!bytes.value.length) return "";
  return bytes.value
    .map((b) => {
      const code = Number.parseInt(b.hex, 16);
      if (CTRL_ASCII[code]) return CTRL_ASCII[code];
      if (code >= 0x20 && code <= 0x7e) return String.fromCharCode(code);
      return `\\x${b.hex}`;
    })
    .join("");
});

const isAsciiFrame = computed(() => encoding.value === "ascii");

const rawModeItems = [
  { label: "原始报文", value: "hex" },
  { label: "ASCII 字符", value: "ascii" },
];

const toast = useToast();

async function copyText(text, okTitle) {
  if (!text) {
    toast.add({ title: "无可复制内容", color: "warning" });
    return;
  }
  try {
    await writeClipboard(text);
    toast.add({ title: okTitle, color: "success" });
  } catch {
    toast.add({ title: "复制失败", color: "error" });
  }
}

async function copyRawHex() {
  await copyText(rawHexSpaced.value || rawHex.value, "已复制原始报文");
}

async function copyRawAscii() {
  await copyText(rawAsciiText.value, "已复制 ASCII 字符");
}

// 展示用精简 JSON：去掉顶层摘要展平与 parsed.raw_hex 等重复
const pretty = computed(() => (message.value ? prettySlimMessage(message.value) : ""));
</script>

<template>
  <UModal
    v-model:open="open"
    :title="message ? `${message.func_code || ''} ${message.func_name || '报文解析'}`.trim() : '报文解析'"
    :description="message ? `${formatAnyToDisplay(message.ts) || ''} · ${message.peer || ''}` : ''"
    :ui="{
      content: 'sm:max-w-4xl w-[min(96vw,56rem)] max-h-[90vh] flex flex-col overflow-hidden',
      body: 'flex-1 min-h-0 p-0 overflow-hidden flex flex-col',
      footer: 'shrink-0',
    }"
    @update:open="(v) => { if (!v) requestClose(); }"
    @after:leave="onAfterLeave"
  >
    <template #body>
      <div v-if="message" class="flex flex-col min-h-0 flex-1 overflow-hidden">
        <div class="shrink-0 border-b border-default px-4 pt-3 pb-3 space-y-3 bg-default">
          <div class="flex flex-wrap gap-2">
            <UBadge v-if="message.func_name" color="primary" variant="subtle">
              {{ message.func_code }} {{ message.func_name }}
            </UBadge>
            <UBadge
              v-if="message.crc_ok === true || message.crc_ok === false"
              :color="message.crc_ok ? 'success' : 'error'"
              variant="subtle"
            >
              CRC {{ message.crc_ok ? "通过" : "失败" }}
            </UBadge>
            <UBadge v-if="message.remote_addr" color="neutral" variant="subtle">
              站址 {{ message.remote_addr }}
            </UBadge>
            <UBadge color="neutral" variant="outline">{{ message.direction }}</UBadge>
            <UBadge :color="encodingColor" variant="outline">{{ encodingLabel }}</UBadge>
            <UBadge color="neutral" variant="outline">{{ bytes.length }} 字节</UBadge>
          </div>

          <UAlert
            v-if="message.error || (parsed?.errors || []).length"
            color="error"
            variant="subtle"
            icon="i-lucide-triangle-alert"
            :title="message.error || (parsed.errors || []).join('; ')"
          />

          <div>
            <div class="flex items-center justify-between gap-2 mb-2">
              <div class="flex items-center gap-2 min-w-0">
                <UTabs
                  v-if="isAsciiFrame"
                  v-model="rawMode"
                  :items="rawModeItems"
                  :content="false"
                  size="xs"
                  class="w-auto"
                />
                <p v-else class="text-xs font-semibold text-muted">原始报文</p>
              </div>
              <div class="flex shrink-0 items-center gap-1.5">
                <UButton
                  size="xs"
                  color="neutral"
                  variant="soft"
                  icon="i-lucide-copy"
                  :disabled="!rawHex"
                  @click="copyRawHex"
                >
                  {{ isAsciiFrame ? "复制 Hex" : "复制" }}
                </UButton>
                <UButton
                  v-if="isAsciiFrame"
                  size="xs"
                  color="neutral"
                  variant="soft"
                  icon="i-lucide-type"
                  :disabled="!rawAsciiText"
                  @click="copyRawAscii"
                >
                  复制 ASCII
                </UButton>
              </div>
            </div>
            <div class="rounded-lg border border-default p-3 max-h-[36vh] overflow-y-auto bg-elevated/30">
              <pre
                v-if="isAsciiFrame && rawMode === 'ascii'"
                class="font-mono text-sm text-toned whitespace-pre-wrap break-all m-0 leading-relaxed"
              >{{ rawAsciiText || "—" }}</pre>
              <HexMap
                v-else
                :bytes="bytes"
                :fields="fields"
                :show-ascii="isAsciiFrame"
                :highlight-id="highlightId"
                :hover-offset="hoverOffset"
                @hover-byte="onHoverByte"
                @leave="onHexLeave"
                @click-field="onClickField"
              />
            </div>
          </div>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
          <div v-for="g in groups" :key="g.key">
            <p class="text-xs font-semibold text-muted mb-2">
              {{ g.label }}
            </p>
            <div class="flex flex-col gap-1">
              <button
                v-for="f in g.items"
                :key="f.id"
                type="button"
                class="flex items-start gap-3 rounded-lg border px-3 py-2 text-left transition"
                :class="
                  highlightId === f.id
                    ? 'border-primary bg-primary/10'
                    : 'border-default hover:bg-elevated'
                "
                @mouseenter="onFieldEnter(f)"
                @mouseleave="onFieldLeave"
                @click="onClickField(f.id)"
              >
                <span
                  class="mt-1 size-2.5 shrink-0 rounded-full"
                  :class="{
                    'bg-primary': f.color === 'primary',
                    'bg-success': f.color === 'success',
                    'bg-info': f.color === 'info',
                    'bg-warning': f.color === 'warning',
                    'bg-error': f.color === 'error',
                    'bg-muted': !f.color || f.color === 'neutral',
                  }"
                />
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-baseline justify-between gap-2">
                    <span class="text-sm font-medium">{{ f.label }}</span>
                    <span class="font-mono text-[10px] text-muted">
                      [{{ f.start }}..{{ f.end - 1 }}]
                    </span>
                  </div>
                  <p class="text-sm text-toned truncate">{{ f.value }}</p>
                  <p class="font-mono text-[11px] text-muted truncate">{{ fieldHex(f) }}</p>
                </div>
              </button>
            </div>
          </div>

          <UAlert
            v-if="!fields.length"
            color="warning"
            variant="subtle"
            title="该记录无字段布局信息"
          />

          <div>
            <UButton
              size="xs"
              color="neutral"
              variant="ghost"
              :icon="showJson ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
              @click="showJson = !showJson"
            >
              {{ showJson ? "收起 JSON" : "查看原始 JSON" }}
            </UButton>
            <div
              v-if="showJson"
              class="mt-2 rounded-lg border border-default p-3 max-h-48 overflow-auto"
            >
              <pre class="font-mono text-xs text-toned whitespace-pre-wrap break-all m-0">{{ pretty }}</pre>
            </div>
          </div>
        </div>
      </div>
    </template>

    <template #footer>
      <div class="flex justify-end w-full">
        <UButton color="neutral" variant="soft" @click="requestClose">关闭</UButton>
      </div>
    </template>
  </UModal>
</template>
