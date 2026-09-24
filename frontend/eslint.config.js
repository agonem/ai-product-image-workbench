import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import {
  defineConfigWithVueTs,
  vueTsConfigs,
} from '@vue/eslint-config-typescript'

export default defineConfigWithVueTs(
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  vue.configs['flat/essential'],
  vueTsConfigs.recommended,
)
