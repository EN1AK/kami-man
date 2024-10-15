import { Context, Schema } from 'koishi';
import fs from 'fs';
import axios from 'axios';
import path from 'path';

export const name = 'ygo-card-search';
export const usage = `
## 命令说明
*  \`ck 卡片名称\` - 查询卡片信息。
*  \`ck -d "类型" 卡片名称\` - 限定类型的查询卡片信息。
*  \`pl 名称\` - 批量查询卡片信息。
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
  const log = (message: string) => { if (config.debug) console.log(message); };

  const handleFileOperation = async (filePath: string, operation: 'load' | 'save', data?: Record<string, string[]>) => {
    try {
      if (operation === 'load') {
        const rawData = await fs.promises.readFile(filePath, 'utf-8');
        replaceConfig = JSON.parse(rawData);
        log('替换规则成功加载:\n' + JSON.stringify(replaceConfig, null, 2));
      } else {
        await fs.promises.writeFile(filePath, JSON.stringify(data, null, 2), 'utf-8');
        log('替换规则已更新并保存至文件:\n' + JSON.stringify(data, null, 2));
      }
    } catch (error) {
      console.error(`文件操作时发生错误: ${error}`);
    }
  };

  const loadReplaceConfig = async () => {
    if (config.enableReplace) {
      const filePath = path.resolve(config.replaceConfigPath);
      await handleFileOperation(filePath, 'load');
    }
  };

  const saveReplaceConfig = async () => {
    const filePath = path.resolve(config.replaceConfigPath);
    await handleFileOperation(filePath, 'save', replaceConfig);
  };

  const replaceCardName = (cardname: string): string => {
    for (const [standardName, aliases] of Object.entries(replaceConfig)) {
      if (aliases.includes(cardname)) return standardName;
    }
    return cardname;
  };

  const formatCardInfo = (card: any): string => {
    const { id, cn_name, md_name, jp_name, en_name, text } = card;
    log('解析的卡片信息:\n' + JSON.stringify(card, null, 2));
    return `
<img src="https://cdn.233.momobako.com/ygopro/pics/${id}.jpg"/>
中文卡名: ${cn_name}
MD卡名: ${md_name}
日文名: ${jp_name}
英文名: ${en_name}
${text.types}
${text.desc}
${text.pdesc ? `灵摆：[${text.pdesc}]` : ''}
    `;
  };

  const filterCardsByType = (cards: any[], typeFilter: string) => {
    return cards.filter(card => !typeFilter || matchCardWithType(card.text.types, typeFilter));
  };

  const matchCardWithType = (types: string, type: string): boolean => {
    const typeArray = type.split(' ').map(t => t.trim().toLowerCase());
    const cardTypeString = types.replace(/[\[\]]/g, '').toLowerCase();
    const atkDefMatch = cardTypeString.match(/(\d+)\/(\d+)/);
    const atk = atkDefMatch ? atkDefMatch[1] : null;
    const def = atkDefMatch ? atkDefMatch[2] : null;
    const pendulumMatch = cardTypeString.match(/(\d+)\/(\d+)/g);
    const pendulum = pendulumMatch ? pendulumMatch[pendulumMatch.length - 1] : null;

    return typeArray.every(t => {
      if (t.startsWith('atk') && atk) return parseInt(t.replace('atk', '')) === parseInt(atk);
      if (t.startsWith('def') && def) return parseInt(t.replace('def', '')) === parseInt(def);
      if (t.startsWith('p') && pendulum) return parseInt(t.replace('p', '')) === parseInt(pendulum);
      return cardTypeString.includes(t);
    });
  };

  const handleApiRequest = async (url: string) => {
    try {
      log(`发起 API 请求: ${url}`);
      const response = await axios.get(url);
      log('API 响应成功，返回数据:\n' + JSON.stringify(response.data, null, 2));
      return response.data.result;
    } catch (error) {
      console.error('API 请求或处理时发生错误:', error);
      log('错误详细信息：' + error.message);
      throw new Error('查询卡片信息时发生错误，请稍后再试。');
    }
  };

  const handleCardQuery = async ({ session, options }: any, cardname: string) => {
    const typeFilter = options['类型限定'] || '';
    log(`收到查询请求，卡片名称: ${cardname}\n类型过滤: ${typeFilter}`);

    if (!cardname) return `错误: 没有提供卡片名称`;

    if (config.enableReplace) {
      const originalName = cardname;
      cardname = replaceCardName(cardname);
      log(originalName !== cardname
        ? `原卡片名称 "${originalName}" 被替换为标准名称: ${cardname}`
        : `卡片名称 "${originalName}" 未找到对应的替换规则，保持原名称。`);
    }

    const cardList = await handleApiRequest(`https://ygocdb.com/api/v0/?search=${encodeURIComponent(cardname)}`);
    if (!cardList || cardList.length === 0) return `未找到卡片：${cardname}`;

    const filteredCards = filterCardsByType(cardList, typeFilter);
    if (filteredCards.length === 0) return `没有找到符合类型过滤条件 "${typeFilter}" 的卡片。`;

    return formatCardInfo(filteredCards[0]);
  };

  const handleBatchQuery = async ({ session, options }: any, cardname: string) => {
    const maxCount = options.最大数量 || 5;
    log(`开始批量查询卡片，卡片名称: ${cardname}，最大查询数量: ${maxCount}`);

    const cardList = await handleApiRequest(`https://ygocdb.com/api/v0/?search=${encodeURIComponent(cardname)}`);
    if (!cardList || cardList.length === 0) return `<message>未找到卡片：${cardname}</message>`;

    log(`返回给用户的结果:\n${cardList.slice(0, maxCount).map(formatCardInfo).join('\n---\n')}`);

    return `<message forward>
              ${cardList.slice(0, maxCount).map(card => `<message>${formatCardInfo(card)}</message>`).join('')}
            </message>`;
  };


  const manageReplaceConfig = async (args: string | undefined, action: 'add' | 'delete') => {
    const [standardName, alias] = args?.split(':').map(s => s.trim()) || [];
    if (!standardName || !alias) return `格式错误，正确格式为：rpcfg ${action} 标准卡名:别名`;

    if (action === 'add') {
      if (!replaceConfig[standardName]) replaceConfig[standardName] = [];
      if (!replaceConfig[standardName].includes(alias)) {
        replaceConfig[standardName].push(alias);
        await saveReplaceConfig();
        return `成功添加替换规则：${alias} -> ${standardName}`;
      }
      return `别名 "${alias}" 已经存在于标准卡名 "${standardName}" 的规则中。`;
    }

    if (action === 'delete') {
      if (!replaceConfig[standardName] || !replaceConfig[standardName].includes(alias)) {
        return `别名 "${alias}" 不存在于标准卡名 "${standardName}" 的规则中。`;
      }
      replaceConfig[standardName] = replaceConfig[standardName].filter(item => item !== alias);
      await saveReplaceConfig();
      return `成功删除替换规则：${alias} -> ${standardName}`;
    }
    return '';
  };

  ctx.command('ck <cardname:text>', '查询游戏王卡片信息')
    .alias('查卡')
    .option('类型限定', '-d [type]', { fallback: '' })
    .action(handleCardQuery);

  ctx.command('pl <cardname:text>', '批量查询卡片信息')
    .alias('批量查卡')
    .option('最大数量', '-n [number]', { fallback: 5 })
    .action(handleBatchQuery);

  ctx.command('rpcfg <action:string> [args:text]', '管理替换规则')
    .action(async ({ session }, action, args) => {
      if (!config.enableReplace) return '替换功能未启用，请在配置中开启。';

      if (action === 'reload') {
        await loadReplaceConfig();
        return '替换规则已重新加载。';
      }

      if (action === 'add' || action === 'delete') {
        return await manageReplaceConfig(args, action);
      }

      return '未知操作，支持的操作有：add、delete、reload。';
    });

  loadReplaceConfig(); // 初始加载替换规则
}
