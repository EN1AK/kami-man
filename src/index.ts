import { Context, Schema } from 'koishi';
import fs from 'fs';
import axios from 'axios';
import path from 'path';


export const name = 'ygo-card-search'
export const usage = `
## 开发中
如有功能建议和意见，欢迎在 [GitHub issues](https://github.com/RikoNeko/koishi-plugin-ygo-card-search/issues) 中提出。

## 替换规则的 JSON 文件格式如下：

*  {
*    "暗黑大法师": "艾克佐迪亚",
*    "黑暗大法师": "艾克佐迪亚",
*    "刻魔": "刻印群魔的刻魔锻冶师"
*  }

前面的键是要被替换的卡片名称，后面的值是替换后的卡片名称。
例如这里，暗黑大法师和黑暗大法师会被替换为艾克佐迪亚，刻魔会被替换为刻印群魔的刻魔锻冶师。
`

interface Config {
  debug: boolean;
  enableReplace: boolean;
  replaceConfigPath: string; 
}

export const Config: Schema<Config> = Schema.object({
  debug: Schema.boolean().default(false).description('调试模式，开启时将在控制台打印详细的运行日志'),
  enableReplace: Schema.boolean().default(false).description('是否启用卡片名称替换功能'),
  replaceConfigPath: Schema.path().description('指定包含卡片名称替换规则的 JSON 文件的目录路径'),
});

export function apply(ctx: Context, config: Config) {
  let replaceConfig: Record<string, string> = {};

  // 加载替换规则的 JSON 文件
  function loadReplaceConfig() {
    if (config.enableReplace) {
      try {
        const replaceConfigFilePath = path.resolve(config.replaceConfigPath);
        const rawData = fs.readFileSync(replaceConfigFilePath, 'utf-8');
        replaceConfig = JSON.parse(rawData);
        if (config.debug) {
          console.log('替换规则成功加载:');
          console.log(replaceConfig);
        }
      } catch (error) {
        console.error('读取替换规则时发生错误:');
        console.error(error);
      }
    }
  }

  // 初始化时加载替换规则
  loadReplaceConfig();

  ctx.command('ck <cardname:string>', '查询游戏王卡片信息')
    .alias('查卡')
    .action(async ({ session }, cardname) => {
      if (config.debug) {
        console.log(`调试模式已开启`);
        console.log(`收到查询请求，卡片名称: ${cardname}`);
      }

      // 检查输入的 cardname 是否为空
      if (!cardname) {
        const message = `错误: 没有提供卡片名称`;
        if (config.debug) console.log(message);
        return message;
      }

      // 根据替换规则替换 cardname（如果启用了替换功能）
      if (config.enableReplace && replaceConfig[cardname]) {
        const originalName = cardname;
        cardname = replaceConfig[cardname];
        if (config.debug) {
          console.log(`原卡片名称 "${originalName}" 根据替换规则被替换为: ${cardname}`);
        }
      } else if (config.enableReplace) {
        if (config.debug) {
          console.log(`卡片名称 "${cardname}" 未找到对应的替换规则，保持原名称。`);
        }
      }

      try {
        // 发起 API 请求
        const url = `https://ygocdb.com/api/v0/?search=${encodeURIComponent(cardname)}`;
        if (config.debug) {
          console.log(`发起 API 请求: ${url}`);
        }

        const response = await axios.get(url);

        // 打印原始响应数据
        if (config.debug) {
          console.log('API 响应成功，返回数据:');
          console.log(response.data);
        }

        // 检查是否有结果返回
        const cardData = response.data.result[0];
        if (!cardData) {
          const message = `未找到卡片：${cardname}`;
          if (config.debug) console.log(message);
          return message;
        }

        // 解构卡片信息
        const { id, cn_name, md_name, jp_name, en_name, text } = cardData;
        const { types, desc } = text;

        if (config.debug) {
          console.log('解析的卡片信息:');
          console.log({
            id, cn_name, md_name, jp_name, en_name, types, desc,
          });
        }

        // 返回格式化的卡片信息
        const result = `
<img src="https://cdn.233.momobako.com/ygopro/pics/${id}.jpg"/>
中文卡名: ${cn_name}
MD卡名: ${md_name}
日文名: ${jp_name}
英文名: ${en_name}
${types}
${desc}
        `;

        if (config.debug) {
          console.log('返回给用户的结果:');
          console.log(result);
        }

        return result;
      } catch (error) {
        // 捕获错误并打印详细信息
        console.error('API 请求或处理时发生错误:');
        console.error(error);

        if (config.debug) {
          console.log('错误详细信息：', error.message);
        }

        return '查询卡片信息时发生错误，请稍后再试。';
      }
    });
}
