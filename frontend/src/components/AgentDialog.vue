<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { json } from '../api/workbench'
import { confirmAction } from '../workbench/confirm'
import type { Agent } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'
import AgentAvatar from './AgentAvatar.vue'
import LineIcon from './LineIcon.vue'
import ModalDialog from './ModalDialog.vue'

// Manage agents (ADR-20261008-L): your own, and the public ones when you are an admin.
const props = defineProps<{ agents: Agent[]; admin: boolean }>()
const emit = defineEmits<{ close: []; changed: [selected?: string] }>()
const w = inject(workbenchKey)!
const editing = ref<Agent | null>(null)
const creating = ref(false)
const busy = ref(false),
  error = ref('')
const form = ref({ name: '', description: '', instructions: '', public: false })
const avatar = ref<Blob | null>(null),
  avatarPreview = ref(''),
  avatarCleared = ref(false)
const version = ref('')
const mine = computed(() => props.agents.filter((agent) => !agent.public))
const shared = computed(() => props.agents.filter((agent) => agent.public))

function start(agent: Agent | null) {
  editing.value = agent
  creating.value = !agent
  form.value = {
    name: agent?.name ?? '',
    description: agent?.description ?? '',
    instructions: agent?.instructions ?? '',
    public: false,
  }
  avatar.value = null
  avatarPreview.value = ''
  avatarCleared.value = false
  error.value = ''
}
function back() {
  editing.value = null
  creating.value = false
  if (avatarPreview.value) URL.revokeObjectURL(avatarPreview.value)
  avatarPreview.value = ''
}
/** A 256 px centred square PNG, small enough for the 512 KB limit. */
async function choose(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  ;(event.target as HTMLInputElement).value = ''
  if (!file) return
  try {
    const bitmap = await createImageBitmap(file)
    const side = Math.min(bitmap.width, bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 256
    canvas
      .getContext('2d')!
      .drawImage(
        bitmap,
        (bitmap.width - side) / 2,
        (bitmap.height - side) / 2,
        side,
        side,
        0,
        0,
        256,
        256,
      )
    avatar.value = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error())),
        'image/png',
      ),
    )
    if (avatarPreview.value) URL.revokeObjectURL(avatarPreview.value)
    avatarPreview.value = URL.createObjectURL(avatar.value)
    avatarCleared.value = false
  } catch {
    error.value = '这张图片无法读取，请换一张 PNG 或 JPEG。'
  }
}
async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const body: Record<string, unknown> = {
      name: form.value.name.trim(),
      description: form.value.description.trim(),
      instructions: form.value.instructions.trim(),
    }
    if (creating.value && props.admin && form.value.public) body.public = true
    const saved = editing.value
      ? await w.api<Agent>(`/agents/${editing.value.id}`, {
          ...json(body),
          method: 'PUT',
        })
      : await w.api<Agent>('/agents', json(body))
    if (avatar.value)
      await w.api(`/agents/${saved.id}/avatar`, {
        method: 'PUT',
        headers: { 'Content-Type': 'image/png' },
        body: avatar.value,
      })
    else if (avatarCleared.value && editing.value?.avatar)
      await w.api(`/agents/${saved.id}/avatar`, { method: 'DELETE' })
    version.value = String(Date.now())
    w.notice = `已保存智能体“${saved.name}”。`
    emit('changed', creating.value ? saved.id : undefined)
    back()
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
  }
}
async function remove(agent: Agent) {
  if (
    !(await confirmAction(
      `删除智能体“${agent.name}”`,
      '删除后不能再选择它；用它生成过的图片和记录不受影响。',
      '删除',
    ))
  )
    return
  try {
    await w.api(`/agents/${agent.id}`, { method: 'DELETE' })
    emit('changed')
  } catch (cause) {
    if (cause instanceof Error) error.value = cause.message
  }
}
</script>

<template>
  <ModalDialog
    :title="
      editing
        ? `编辑智能体：${editing.name}`
        : creating
          ? '新建智能体'
          : '管理智能体'
    "
    wide
    @close="emit('close')"
  >
    <p v-if="error" class="banner error" role="alert">
      <LineIcon name="alert" :size="14" />{{ error }}
    </p>
    <form
      v-if="editing || creating"
      id="agent-form"
      class="form-grid agent-form"
      @submit.prevent="save"
    >
      <div class="agent-face">
        <span class="agent-avatar large" v-if="avatarPreview"
          ><img :src="avatarPreview" alt=""
        /></span>
        <AgentAvatar
          v-else
          :agent="
            avatarCleared
              ? { id: editing?.id, name: form.name || '?', avatar: false }
              : {
                  id: editing?.id,
                  name: form.name || '?',
                  avatar: editing?.avatar,
                }
          "
          :size="64"
          :version="version"
        />
        <label class="btn sm"
          >上传头像<input
            type="file"
            accept="image/*"
            class="sr-only"
            aria-label="上传头像"
            @change="choose"
        /></label>
        <button
          v-if="avatarPreview || (editing?.avatar && !avatarCleared)"
          type="button"
          class="btn sm"
          @click="
            ((avatar = null), (avatarPreview = ''), (avatarCleared = true))
          "
        >
          去掉头像
        </button>
      </div>
      <label class="form-row"
        ><span>名称</span
        ><input
          v-model="form.name"
          maxlength="20"
          required
          placeholder="例如：Gloria"
      /></label>
      <label class="form-row"
        ><span>一句话介绍</span
        ><input
          v-model="form.description"
          maxlength="60"
          placeholder="例如：电商主图设计师，构图干净、主体突出"
      /></label>
      <label class="form-row"
        ><span>设定（人设、擅长、出图偏好）</span
        ><textarea
          v-model="form.instructions"
          rows="6"
          maxlength="2000"
          required
          placeholder="例如：你是资深母婴电商主图设计师。画面干净明亮，商品是主角；配色柔和统一；道具少而精……"
        ></textarea>
      </label>
      <label v-if="creating && admin" class="check-row"
        ><input
          v-model="form.public"
          type="checkbox"
        />设为公共智能体（所有人可用）</label
      >
      <p class="hint">
        不开魔法棒时，设定会和你的描述一起交给出图模型；打开魔法棒时，文本模型会按设定把描述改写成专业的画面描述再出图。
      </p>
    </form>
    <div v-else class="agent-manage">
      <div class="agent-group">
        <div class="agent-group-head">
          <b>我的智能体</b>
          <button
            type="button"
            class="btn sm primary"
            data-testid="agent-new"
            @click="start(null)"
          >
            <LineIcon name="plus" :size="14" />新建
          </button>
        </div>
        <div
          v-for="agent in mine"
          :key="agent.id"
          class="agent-line"
          data-testid="agent-line"
        >
          <AgentAvatar :agent="agent" :size="36" :version="version" />
          <span class="meta"
            ><b>{{ agent.name }}</b
            ><small>{{ agent.description }}</small></span
          >
          <button
            type="button"
            class="icon-btn"
            :aria-label="`编辑智能体 ${agent.name}`"
            @click="start(agent)"
          >
            <LineIcon name="edit" :size="14" />
          </button>
          <button
            type="button"
            class="icon-btn danger"
            :aria-label="`删除智能体 ${agent.name}`"
            @click="remove(agent)"
          >
            <LineIcon name="del" :size="14" />
          </button>
        </div>
        <p v-if="!mine.length" class="hint">
          还没有自己的智能体。新建一个，写下你常用的风格要求，以后一键选用。
        </p>
      </div>
      <div class="agent-group">
        <div class="agent-group-head">
          <b>公共智能体</b>
          <small v-if="!admin" class="hint">由管理员维护</small>
        </div>
        <div
          v-for="agent in shared"
          :key="agent.id"
          class="agent-line"
          data-testid="agent-line"
        >
          <AgentAvatar :agent="agent" :size="36" :version="version" />
          <span class="meta"
            ><b>{{ agent.name }}</b
            ><small>{{ agent.description }}</small></span
          >
          <template v-if="agent.editable">
            <button
              type="button"
              class="icon-btn"
              :aria-label="`编辑智能体 ${agent.name}`"
              @click="start(agent)"
            >
              <LineIcon name="edit" :size="14" />
            </button>
            <button
              type="button"
              class="icon-btn danger"
              :aria-label="`删除智能体 ${agent.name}`"
              @click="remove(agent)"
            >
              <LineIcon name="del" :size="14" />
            </button>
          </template>
        </div>
      </div>
    </div>
    <template #footer>
      <template v-if="editing || creating">
        <button type="button" class="btn" @click="back">返回</button>
        <button
          type="submit"
          form="agent-form"
          class="btn primary"
          :disabled="busy"
        >
          保存智能体
        </button>
      </template>
      <button v-else type="button" class="btn" @click="emit('close')">
        完成
      </button>
    </template>
  </ModalDialog>
</template>
