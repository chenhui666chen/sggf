/**
 * 开发环境专用日志工具
 * 
 * 生产环境自动禁用所有日志输出，提升性能并防止信息泄露
 * 开发环境保留完整的调试能力
 */

const isDevelopment = import.meta.env.MODE === 'development'

export const logger = {
  /**
   * 普通日志
   */
  log: (...args: any[]) => {
    if (isDevelopment) {
      console.log(...args)
    }
  },

  /**
   * 错误日志
   */
  error: (...args: any[]) => {
    if (isDevelopment) {
      console.error(...args)
    } else {
      // 生产环境也记录错误（但不输出到控制台）
      // 可以发送到错误监控服务
      // sendToErrorTracking(args)
    }
  },

  /**
   * 警告日志
   */
  warn: (...args: any[]) => {
    if (isDevelopment) {
      console.warn(...args)
    }
  },

  /**
   * 信息日志
   */
  info: (...args: any[]) => {
    if (isDevelopment) {
      console.info(...args)
    }
  },

  /**
   * 调试日志
   */
  debug: (...args: any[]) => {
    if (isDevelopment) {
      console.debug(...args)
    }
  },

  /**
   * 表格日志
   */
  table: (data: any) => {
    if (isDevelopment) {
      console.table(data)
    }
  },

  /**
   * 计时开始
   */
  time: (label: string) => {
    if (isDevelopment) {
      console.time(label)
    }
  },

  /**
   * 计时结束
   */
  timeEnd: (label: string) => {
    if (isDevelopment) {
      console.timeEnd(label)
    }
  }
}

export default logger
