import { Context, Schema } from 'koishi';
import fs from 'fs';
import axios from 'axios';
import path from 'path';

export const name = 'ygo-card-search';
export const usage = `
## 命令说明
*  \`ck 卡片名称\` - 查询卡片信息。
*  \`rpcfg add 标准卡名:别名\` - 添加替换规则。
*  \`rpcfg delete 标准卡名:别名\` - 删除替换规则。
*  \`rpcfg reload\` - 重新加载替换规则。

## 替换规则的 JSON 文件格式如下：

\`\`\`
{
  "艾克佐迪亚": [
    "暗黑大法师",
    "黑暗大法师"
    ],
  "刻印群魔的刻魔锻冶师": ["刻魔"]
}
\`\`\`
`;

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
  let replaceConfig: Record<string, string[]> = {};

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

  function saveReplaceConfig() {
    try {
      const replaceConfigFilePath = path.resolve(config.replaceConfigPath);
      fs.writeFileSync(replaceConfigFilePath, JSON.stringify(replaceConfig, null, 2), 'utf-8');
      if (config.debug) {
        console.log('替换规则已更新并保存至文件:');
        console.log(replaceConfig);
      }
    } catch (error) {
      console.error('保存替换规则时发生错误:');
      console.error(error);
    }
  }

  loadReplaceConfig();

  ctx.command('ck <cardname:string>', '查询游戏王卡片信息')
    .alias('查卡')
    .action(async ({ session }, cardname) => {
      if (config.debug) {
        console.log(`调试模式已开启`);
        console.log(`收到查询请求，卡片名称: ${cardname}`);
      }

      if (!cardname) {
        const message = `错误: 没有提供卡片名称`;
        if (config.debug) console.log(message);
        return message;
      }

      if (config.enableReplace) {
        let replaced = false;

        for (const [standardName, aliases] of Object.entries(replaceConfig)) {
          if (aliases.includes(cardname)) {
            const originalName = cardname;
            cardname = standardName;
            replaced = true;

            if (config.debug) {
              console.log(`原卡片名称 "${originalName}" 被替换为标准名称: ${cardname}`);
            }

            break; 
          }
        }

        if (!replaced && config.debug) {
          console.log(`卡片名称 "${cardname}" 未找到对应的替换规则，保持原名称。`);
        }
      }

      try {
        const url = `https://ygocdb.com/api/v0/?search=${encodeURIComponent(cardname)}`;
        if (config.debug) {
          console.log(`发起 API 请求: ${url}`);
        }

        const response = await axios.get(url);

        if (config.debug) {
          console.log('API 响应成功，返回数据:');
          console.log(response.data);
        }

        const cardData = response.data.result[0];
        if (!cardData) {
          const message = `未找到卡片：${cardname}`;
          if (config.debug) console.log(message);
          return message;
        }

        const { id, cn_name, md_name, jp_name, en_name, text } = cardData;
        const { types, pdesc, desc } = text;

        if (config.debug) {
          console.log('解析的卡片信息:');
          console.log({
            id, cn_name, md_name, jp_name, en_name, types, pdesc, desc,
          });
        }

        const result = `
<img src="https://cdn.233.momobako.com/ygopro/pics/${id}.jpg"/>
中文卡名: ${cn_name}
MD卡名: ${md_name}
日文名: ${jp_name}
英文名: ${en_name}
${types}
${desc}
${pdesc ? `灵摆：[${pdesc}]` : ''}
        `;

        if (config.debug) {
          console.log('返回给用户的结果:');
          console.log(result);
        }

        return result;
      } catch (error) {
        console.error('API 请求或处理时发生错误:');
        console.error(error);

        if (config.debug) {
          console.log('错误详细信息：', error.message);
        }

        return '查询卡片信息时发生错误，请稍后再试。';
      }
    });

  ctx.command('rpcfg <action:string> [args:text]', '管理替换规则')
    .action(({ session }, action, args) => {
      if (!config.enableReplace) {
        return '替换功能未启用，请在配置中开启。';
      }
  
      switch (action) {
        case 'add': {
          const [standardName, alias] = args?.split(':').map(s => s.trim()) || [];
          if (!standardName || !alias) {
            return '格式错误，正确格式为：rpcfg add 标准卡名:别名';
          }
  
          // 如果 replaceConfig 中没有此标准卡名，创建一个空的数组
          if (!replaceConfig[standardName]) {
            replaceConfig[standardName] = [];
          }
  
          // 检查别名是否已经存在，防止重复添加
          if (!replaceConfig[standardName].includes(alias)) {
            replaceConfig[standardName].push(alias);
            saveReplaceConfig();
            return `成功添加替换规则：${alias} -> ${standardName}`;
          } else {
            return `别名 "${alias}" 已经存在于标准卡名 "${standardName}" 的规则中。`;
          }
        }
  
        case 'delete': {
          const [standardName, alias] = args?.split(':').map(s => s.trim()) || [];
          if (!standardName || !alias) {
            return '格式错误，正确格式为：rpcfg delete 标准卡名:别名';
          }
  
          // 确认是否存在对应的标准卡名及其别名
          if (!replaceConfig[standardName] || !replaceConfig[standardName].includes(alias)) {
            return `别名 "${alias}" 不存在于标准卡名 "${standardName}" 的规则中。`;
          }
  
          // 从别名数组中删除指定别名
          replaceConfig[standardName] = replaceConfig[standardName].filter(item => item !== alias);
          saveReplaceConfig();
          return `成功删除替换规则：${alias} -> ${standardName}`;
        }
  
        case 'reload': {
          // 重新加载配置文件
          loadReplaceConfig();
          return '替换规则已重新加载。';
        }
  
        default: {
          return '未知操作，支持的操作有：add、delete、reload。';
        }
      }
    });
}
