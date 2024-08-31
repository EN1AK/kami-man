import axios from 'axios';
import { Context, Schema } from 'koishi'

export const name = 'ygo-card-search'

export const usage = `
## 开发中
这插件是花了十几分钟手搓的试验品，功能不全，目前不建议任何人安装使用。
如果你想参与开发完善，请联系QQ：2371567590
`

export interface Config {}
export const Config: Schema<Config> = Schema.object({})

export function apply(ctx: Context) {
  ctx.command('ck <cardname:string>', '查询游戏王卡片信息')
    .alias('查卡')
    .action(async ({ session }, cardname) => {
      try {
        const response = await axios.get(`https://ygocdb.com/api/v0/?search=${encodeURIComponent(cardname)}`);
        const cardData = response.data.result[0];

        if (!cardData) {
          return `未找到卡片：${cardname}`;
        }

        const { id, cn_name, md_name, jp_name, en_name, text } = cardData;
        const { types, desc } = text;

        return `
卡片ID: ${id}
中文卡名: ${cn_name}  MD卡名: ${md_name}
日文名: ${jp_name}  英文名: ${en_name}
类型: ${types}
描述: ${desc}
        `;
      } catch (error) {
        console.error(error);
        return '查询卡片信息时发生错误，请稍后再试。';
      }
    });
};


