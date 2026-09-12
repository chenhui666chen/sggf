import type { ReactNode } from 'react'
import {
  Box,
  Link,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'

// P2-5.5：隐私政策正文（v2，2026-09-05 生效）。
// 本组件为展示正文唯一维护点：全文页（/privacy）与页内弹窗（PrivacyPolicyDialog）共用；
// 后端 app/services/consent_service.py 的 PRIVACY_POLICY_V2_TEXT 为存证同源文本，须同步维护。
// 政策文本变更时须升级同意版本（前后端 CONSENT_VERSIONS / CURRENT_CONSENT_VERSIONS）让用户重新勾选。

function SectionHeading({ children }: { children: string }) {
  return (
    <Typography variant="h6" fontWeight="bold" sx={{ mt: 4, mb: 1.5 }}>
      {children}
    </Typography>
  )
}

function Para({ children }: { children: ReactNode }) {
  return (
    <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5, lineHeight: 1.9 }}>
      {children}
    </Typography>
  )
}

function Bullet({ children }: { children: ReactNode }) {
  return (
    <Typography variant="body2" color="text.secondary" component="li" sx={{ lineHeight: 1.9 }}>
      {children}
    </Typography>
  )
}

export default function PrivacyPolicyContent() {
  return (
    <>
      <Typography variant="h4" fontWeight="bold" gutterBottom>
        拾光工坊隐私政策
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        版本：v2 · 生效日期：2026 年 9 月 5 日
      </Typography>

      <Para>
        拾光工坊（下称"本服务"）是一个面向创作者的 AI 写作、有声书制作与短剧制作工具，由南京拾光工坊信息科技有限公司（下称"我们"）运营。对你产生的媒体资产（图片、视频、音频），本服务默认采用"本地优先"存储：资产副本默认保存在你的设备本地，服务端仅保存必要的元数据与用于功能实现的受控副本。我们深知个人信息对你的重要性，将以本政策说明我们如何收集、使用、存储、共享与保护你的个人信息，以及你可以如何管理。
      </Para>
      <Para>请在注册前仔细阅读本政策。勾选同意本政策即表示你已充分理解并接受其全部内容。</Para>
      <Para>
        单独同意提示：本政策是对个人信息处理活动的整体告知。当处理涉及敏感个人信息（如手机号），或需要将你的内容提供给第三方
        AI 服务商处理（见第四节）时，我们会在对应操作界面另行说明处理细节，并通过独立的勾选框取得你的单独同意；在你完成该等勾选前，我们不会进行相应处理。你可以在"用户中心 → 同意记录"随时查看与撤回各项同意。
      </Para>

      <SectionHeading>一、我们收集的个人信息</SectionHeading>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>信息类型</TableCell>
              <TableCell>是否必需</TableCell>
              <TableCell>对应同意项</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell>账户标识：用户名、邮箱</TableCell>
              <TableCell>必需</TableCell>
              <TableCell>《隐私政策》</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>账户展示：昵称（默认同用户名）、头像</TableCell>
              <TableCell>选填</TableCell>
              <TableCell>《隐私政策》</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>登录凭据：密码（仅存 bcrypt 不可逆哈希）</TableCell>
              <TableCell>密码登录时必需</TableCell>
              <TableCell>《隐私政策》</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>手机号（敏感个人信息）</TableCell>
              <TableCell>选填</TableCell>
              <TableCell>《隐私政策》+ 手机号收集单独同意</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>第三方标识：支付宝 openid / 微信 openid / 微信 unionid</TableCell>
              <TableCell>使用第三方登录时</TableCell>
              <TableCell>第三方资料同步单独同意</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>安全审计：IP 地址、User-Agent</TableCell>
              <TableCell>必需（安全目的）</TableCell>
              <TableCell>《隐私政策》</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>创作内容（文本）：小说/剧本文本、分镜与画面描述</TableCell>
              <TableCell>使用对应功能时</TableCell>
              <TableCell>《隐私政策》</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>媒体资产（图片/视频/音频）：你生成或上传的图片、视频、音频素材及音色配置</TableCell>
              <TableCell>使用对应功能时</TableCell>
              <TableCell>《隐私政策》（媒体资产默认本地存储，见第三节）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>验证码：邮箱验证码、短信验证码</TableCell>
              <TableCell>对应操作时</TableCell>
              <TableCell>《隐私政策》</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>

      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        我们不收集
      </Typography>
      <Para>
        真实姓名、身份证号、年龄/出生日期、位置信息、通讯录、生物识别信息（TTS
        音色素材仅用于配音生成，不用于声纹识别，不构成生物识别信息）。
      </Para>

      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        年龄核验方式
      </Typography>
      <Para>
        我们不收集年龄、出生日期等信息（见上文"我们不收集"）。为执行本政策第八节所述未成年人限制，注册或首次创建账户时，你需要勾选"我已年满
        14 周岁"的自我声明。该勾选属于使用资格确认，不构成年龄、出生日期等个人信息的收集；勾选记录将作为一条同意/声明记录留存（见第三节"同意记录"与第八节）。
      </Para>

      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        第三方标识的存储方式
      </Typography>
      <Para>
        openid/unionid
        在数据库中以"确定性查找哈希 + 加密密文"双字段存储，不落明文；密钥与数据分离保管。据此我们无法直接看到明文标识，等值匹配通过哈希完成。
      </Para>
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        安全审计字段
      </Typography>
      <Para>
        IP 地址与 User-Agent 仅在安全审计日志中存储哈希值（加盐
        HMAC），不存原文，保留 90 天后自动删除。
      </Para>

      <SectionHeading>二、我们如何使用个人信息</SectionHeading>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>目的</TableCell>
              <TableCell>使用的信息</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell>注册与登录认证</TableCell>
              <TableCell>邮箱/用户名/手机号、密码哈希、第三方标识</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>邮箱/短信验证与密码找回</TableCell>
              <TableCell>邮箱、手机号、验证码（短期有效且不回显；输入手机号走短信通道，输入邮箱/用户名走邮件通道）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>账户资料展示</TableCell>
              <TableCell>昵称、头像</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>AI 创作功能</TableCell>
              <TableCell>你提交的小说/剧本文本（经境内 AI 服务商处理，见第四节）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>有声书制作</TableCell>
              <TableCell>剧本文本、音频素材、音色配置</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>短剧制作</TableCell>
              <TableCell>
                章节文本、剧本/分镜、画面提示词与素材、对白文本与音色配置（生成分镜/关键帧/视频片段、配音并合成短剧成片，图像与视频生成见第四节）
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell>安全防护</TableCell>
              <TableCell>IP、User-Agent（哈希）、登录事件（防暴力破解、账号锁定、异常检测、安全审计）</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        手机号绑定与所有权主张规则
      </Typography>
      <Para>
        手机号为选填的敏感个人信息，仅在取得你的单独同意后处理。如果你输入的手机号已被其他账户绑定，你可以通过短信验证码主张对该号码的所有权；验证通过后，该号码的绑定权转移至你的账户，原账户的手机号字段被清空（其邮箱/用户名等其他登录方式保留），我们会向原账户的注册邮箱发送解绑通知邮件。
      </Para>
      <Para>
        我们不会将你的个人信息用于上述目的之外的用途；超出范围使用前会再次征得你的同意。
      </Para>

      <SectionHeading>三、我们如何存储个人信息</SectionHeading>
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        存储方式与地点：本服务按数据类型分层存储
      </Typography>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>数据类型</TableCell>
              <TableCell>存储位置</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell>账户与文本内容（账号、小说/剧本文本、分镜、积分等）</TableCell>
              <TableCell>境内服务器（数据库为境内节点）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>媒体资产（图片/视频/音频）</TableCell>
              <TableCell>
                默认保存在你的设备本地（浏览器本地存储 OPFS/IndexedDB，或你授权指定的本地目录）；服务端仅保存元数据与来源地址
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell>媒体资产的云端副本</TableCell>
              <TableCell>仅当你选择收录至平台、需要跨设备访问或平台受控保存时，副本存于境内对象存储/服务器</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>生成处理中的临时文件</TableCell>
              <TableCell>仅在 AI 处理期间暂存于境内服务器，任务结束或过期后删除</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
      <Para>
        本地优先提示：媒体资产副本保存在你的设备上，清除浏览器数据、更换设备或删除应用数据可能导致本地副本丢失；服务端元数据与来源地址仍保留，你可据此重新收录或回源获取。
      </Para>
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        保存期限
      </Typography>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableBody>
            <TableRow>
              <TableCell>账户信息</TableCell>
              <TableCell>账户存续期间</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>注销后的账户信息</TableCell>
              <TableCell>
                30 天冷静期后匿名化处理（用户名替换为不可还原的随机标识，邮箱/手机号/密码/第三方标识全部删除）
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell>同意记录</TableCell>
              <TableCell>永久保留（作为已取得同意的证明，匿名化处理保留）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>安全审计日志（IP/UA 哈希）</TableCell>
              <TableCell>90 天，到期自动删除</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>验证码</TableCell>
              <TableCell>数分钟级短期有效，过期自动删除</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>账单与计费记录</TableCell>
              <TableCell>
                依法保存 7 年；其中与计费无关、可直接识别身份的附加信息将删除或去标识化，仅保留财税核验所必需的交易与支付凭证字段
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell>密码</TableCell>
              <TableCell>仅存不可逆哈希，任何情况下不可还原</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>媒体资产（你设备上的本地副本）</TableCell>
              <TableCell>存续于你的设备；清除浏览器数据可能导致丢失</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>媒体资产（服务端元数据与云端副本）</TableCell>
              <TableCell>账户存续期间；账户注销后按"注销后的账户信息"处理，云端副本一并删除</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>生成处理中的临时文件</TableCell>
              <TableCell>处理完成或过期后自动删除</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>

      <SectionHeading>四、我们如何共享个人信息</SectionHeading>
      <Para>
        我们仅在以下情形向境内第三方服务商传输必要信息，均不涉及个人信息出境：
      </Para>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>服务商</TableCell>
              <TableCell>共享内容</TableCell>
              <TableCell>用途</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell>支付宝</TableCell>
              <TableCell>应用标识、授权码（不含你的密码）</TableCell>
              <TableCell>第三方登录的身份验证</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>微信</TableCell>
              <TableCell>应用标识、授权码（不含你的密码）</TableCell>
              <TableCell>第三方登录的身份验证</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>AI 文本服务商（DeepSeek）</TableCell>
              <TableCell>你主动提交的小说/剧本文本</TableCell>
              <TableCell>AI 写作的编辑与生成</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>AI 服务商（阿里云百炼，含通义/万相/qwen 系列模型）</TableCell>
              <TableCell>
                章节文本、剧本/分镜、画面提示词与素材图、配音对白与音色配置、用于内容安全/质量审查的生成图片与视频
              </TableCell>
              <TableCell>短剧各环节生成（剧本/分镜、图像与视频、配音）与内容安全审查</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>AI 服务商（火山引擎/豆包）</TableCell>
              <TableCell>你提交的剧本文本、画面提示词与参考图</TableCell>
              <TableCell>AI 生成、有声书制作与短剧图像/视频生成（当你选用其图像/视频模型时）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>视频生成服务商（可灵 KlingAI）</TableCell>
              <TableCell>素材库同步（角色/场景名称、外观描述、立绘图）；视频生成（画面提示词与首尾帧/参考图）</TableCell>
              <TableCell>短剧视频生成与素材库同步（当你启用同步或选用该引擎时）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>视频生成服务商（Vidu）</TableCell>
              <TableCell>画面提示词与参考图</TableCell>
              <TableCell>短剧视频生成（当你选用该模型时）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>对象存储服务商（阿里云 OSS）</TableCell>
              <TableCell>你选择收录至平台或平台受控保存的图片/视频/音频素材</TableCell>
              <TableCell>文件存储（仅在你选择云端收录或平台受控保存时启用）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>电子邮件系统</TableCell>
              <TableCell>邮箱地址、验证码</TableCell>
              <TableCell>发送验证码与安全通知（邮件由运营者通过自建 SMTP 服务器直接发送，不委托第三方邮件服务商）</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>短信服务商（阿里云短信）</TableCell>
              <TableCell>手机号、验证码</TableCell>
              <TableCell>发送短信验证码与安全通知（通过阿里云短信服务下发）</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        接收方隐私政策入口
      </Typography>
      <Para>
        以上服务商在你将信息提供给其处理时，以其自身隐私政策/隐私保护规则为准。你可以通过下列官方入口了解其对个人信息的处理规则与联系渠道（如入口地址更新，以其官网最新展示为准）：
      </Para>
      <Box component="ul" sx={{ pl: 3, mb: 2 }}>
        <Bullet>
          支付宝：
          <Link href="https://render.alipay.com/p/f/privacy_policies/indexnovs2bqblc.html" target="_blank" rel="noopener noreferrer">
            官方隐私权政策
          </Link>
        </Bullet>
        <Bullet>
          微信（腾讯）：
          <Link href="https://privacy.qq.com" target="_blank" rel="noopener noreferrer">
            腾讯隐私保护平台
          </Link>
        </Bullet>
        <Bullet>
          DeepSeek：
          <Link href="https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html" target="_blank" rel="noopener noreferrer">
            官方隐私政策
          </Link>
        </Bullet>
        <Bullet>
          阿里云百炼 / 阿里云 OSS / 阿里云短信：
          <Link
            href="https://terms.aliyun.com/legal-agreement/terms/suit_bu1_ali_cloud/suit_bu1_ali_cloud202107091605_49213.html"
            target="_blank"
            rel="noopener noreferrer"
          >
            阿里云法律声明及隐私权政策
          </Link>
        </Bullet>
        <Bullet>
          火山引擎/豆包：
          <Link href="https://www.volcengine.cn/docs/6256/64902" target="_blank" rel="noopener noreferrer">
            火山引擎隐私政策
          </Link>
        </Bullet>
        <Bullet>
          可灵 KlingAI：
          <Link href="https://klingai.com/docs/privacy-policy" target="_blank" rel="noopener noreferrer">
            可灵 AI 隐私政策
          </Link>
        </Bullet>
        <Bullet>
          Vidu：
          <Link href="https://www.vidu.cn" target="_blank" rel="noopener noreferrer">
            Vidu 官网（隐私政策入口）
          </Link>
        </Bullet>
      </Box>
      <Para>
        我们将以各服务商公开信息及书面确认为依据，在本政策后续更新版本中补充其作为信息接收方的注册主体全称与联系方式；你也可通过第十节邮箱向我们索取当前名单。上述说明不代表向其传输个人信息的同意以链接有效为前提，第四节表格及"本地优先与共享的边界"仍为完整告知。
      </Para>
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        本地优先与共享的边界
      </Typography>
      <Para>
        媒体资产副本默认保存在你的设备本地，不因账号使用而持续上传。仅在以下情形才会向第三方传输：你使用 AI 生成/编辑功能（传输该次任务所需的内容）、你选择将素材收录至平台或平台受控保存、你主动将素材库同步至可灵。相关服务商仅在对应功能发生时接收当次必要内容，处理完成后即清理，不长期留存你的素材库。
      </Para>
      <Para>
        我们对以上服务商签署数据处理/保密约定，要求其仅为本政策所述目的处理信息并采取同等安全措施。我们不会向任何第三方出售你的个人信息。
      </Para>
      <Para>
        除上述情形外，仅在以下法定情形下共享：取得你的单独同意；为订立/履行合同所必需；履行法定义务；应对公共安全事件等法律法规规定的情形。
      </Para>

      <SectionHeading>五、Cookie 与同类技术</SectionHeading>
      <Para>本服务使用 Cookie 维持登录状态与安全防护，不用于广告跟踪：</Para>
      <Box component="ul" sx={{ pl: 3, mb: 2 }}>
        <Bullet>登录态令牌：仅浏览器可读（httpOnly）+ SameSite=Lax，维持登录，JavaScript 无法读取；</Bullet>
        <Bullet>刷新令牌：仅浏览器可读（httpOnly）+ SameSite=Lax，静默续期登录状态；</Bullet>
        <Bullet>CSRF 令牌：SameSite=Strict，防"跨站伪造请求"攻击的安全校验。</Bullet>
      </Box>
      <Para>你可以通过浏览器设置清除 Cookie，但这将导致需要重新登录。</Para>
      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
        本地存储技术
      </Typography>
      <Para>
        为实现媒体资产的"本地优先"存储，本服务还使用浏览器本地存储（OPFS、IndexedDB）在你的设备上保存媒体资产副本；在你授权后，也可将副本写入你指定的本地目录（文件系统访问 API）。这些数据保存在你的设备上，我们无法直接访问；你可在"用户中心"随时清理本地副本。清除浏览器数据将删除这些本地副本（服务端元数据与来源地址仍保留）。
      </Para>

      <SectionHeading>六、你的权利</SectionHeading>
      <Para>按相关法律，你对个人信息享有以下权利，可通过产品功能或联系个人信息保护负责人行使：</Para>
      <Box component="ol" sx={{ pl: 3, mb: 2 }}>
        <Bullet>
          查阅与更正：在“用户中心 → 账户与安全”查看并修改昵称、头像、手机号、绑定关系；手机号绑定与变更（含第二节所述所有权主张）通过短信验证流程办理；
        </Bullet>
        <Bullet>
          导出：使用"导出我的数据"功能（用户中心），获取你的个人信息与同意记录副本；
        </Bullet>
        <Bullet>
          删除：通过"注销账户"发起删除。为防误操作并处理未完结交易与未消耗权益，账户注销后进入 30
          天冷静期，期满后匿名化处理，服务端保存的媒体资产云端副本一并删除；冷静期内可随时联系负责人撤回注销。如你确认账户无未完结交易且无未消耗权益，希望立即删除个人信息的，可联系个人信息保护负责人申请即时删除，我们将在
          15 个工作日内删除服务端个人信息（存在法定留存义务的字段除外）；
        </Bullet>
        <Bullet>
          撤回同意：你可随时在"用户中心 → 同意记录"查看各项同意的历史；撤回单项同意可联系负责人，或通过注销账户撤回全部同意。撤回不影响撤回前基于同意的处理；
        </Bullet>
        <Bullet>
          注销：注销后我们将停止为你提供服务，并按第三节所述期限与方式处理服务端信息。注销作用于服务端保存的信息，存于你设备本地的媒体资产副本不随注销删除，你可在设备端自行删除；
        </Bullet>
        <Bullet>
          管理本地副本：你可在"用户中心"查看、清理或重新收录保存在设备本地的媒体资产副本；清理本地副本不影响服务端元数据与来源地址。
        </Bullet>
      </Box>
      <Para>我们将在 15 个工作日内响应你的请求。</Para>

      <SectionHeading>七、你的内容责任与保证</SectionHeading>
      <Para>你应对通过本服务提交、上传或生成的内容承担相应责任，并确认知悉与同意：</Para>
      <Box component="ol" sx={{ pl: 3, mb: 2 }}>
        <Bullet>
          权利保证：你对上传的文本、图片、音频、视频及参考素材拥有合法权利，或已取得权利人及必要第三方（含肖像权、声音权、著作权等权利人）的授权，不侵犯任何人的合法权益；你不使用他人未授权的声音进行音色克隆、复刻或模仿，不冒充真实人物，不暗示任何人为你的内容背书；
        </Bullet>
        <Bullet>
          内容合法：你不会利用本服务制作、上传、发布违法或违背公序良俗的内容，不利用深度合成技术从事诈骗、诽谤、侵犯他人个人信息等违法活动，并遵守《生成式人工智能服务管理暂行办法》《互联网信息服务深度合成管理规定》等适用法律法规；
        </Bullet>
        <Bullet>
          生成内容标识：为落实生成式人工智能与深度合成内容标识要求，你知悉并同意本服务及其所用 AI
          服务商可能对生成的图片、视频、音频添加显性标识（如水印、角标）或元数据标识，你不去除、篡改或规避上述标识；
        </Bullet>
        <Bullet>
          审核与处置：为保障内容安全，我们可能对生成内容进行审核，其中部分审核由境内 AI
          服务商承担（见第四节）。如你违反本节义务，我们有权删除相关内容、暂停或终止为你提供服务；给他人造成损害的，由你依法承担相应责任；
        </Bullet>
        <Bullet>
          本地资产说明：保存在你设备本地的媒体资产，不会因正常使用被自动上传；仅在你主动使用 AI
          功能或选择同步、收录时传输必要内容（见第三节、第四节）。
        </Bullet>
      </Box>

      <SectionHeading>八、未成年人保护</SectionHeading>
      <Para>本服务不面向不满 14 周岁的未成年人。</Para>
      <Box component="ul" sx={{ pl: 3, mb: 2 }}>
        <Bullet>
          注册或首次创建账户时，你必须勾选"我已年满 14 周岁"的自我声明，未勾选将无法注册（见第一节"年龄核验方式"）；
        </Bullet>
        <Bullet>我们不收集年龄、出生日期等信息；</Bullet>
        <Bullet>
          已满 14 周岁但未满 18 周岁的未成年人使用本服务，应在监护人同意与指导下进行；如未成年人在监护人陪同下使用本服务，请监护人先行阅读并同意本政策；
        </Bullet>
        <Bullet>
          如果我们发现或有合理理由怀疑使用人不满 14 周岁的，有权暂停或终止提供服务，核实后将注销账户并立即匿名化其个人信息（不适用常规 30 天冷静期），同时删除相应的服务端数据；
        </Bullet>
        <Bullet>
          若你发现我们在不知情的情况下收集了未成年人的个人信息，请通过第十节联系方式联系我们，我们将尽快删除。
        </Bullet>
      </Box>

      <SectionHeading>九、本政策如何更新</SectionHeading>
      <Box component="ul" sx={{ pl: 3, mb: 2 }}>
        <Bullet>本政策变更时，我们会通过站内公告或电子邮件通知你；</Bullet>
        <Bullet>
          在收集范围、使用目的、共享对象等发生重大变化时，我们将在你下次登录时重新征得你的同意（届时你需要重新勾选确认，同意记录将按版本留存）；
        </Bullet>
        <Bullet>你可以在"用户中心 → 同意记录"查看你接受过的每一版政策的版本与时间。</Bullet>
      </Box>

      <SectionHeading>十、如何联系我们</SectionHeading>
      <Para>个人信息保护负责人邮箱：371640372@qq.com</Para>
      <Para>我们将在 15 个工作日内回复。</Para>
      <Para>
        如果你对我们的处理有异议，还可以向履行个人信息保护职责的部门（网信部门）投诉、举报。
      </Para>
    </>
  )
}
