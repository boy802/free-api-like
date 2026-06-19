"""
Telegram Bot - Main Bot Module
Handles all Telegram bot commands and interactions
"""
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from telegram.error import TelegramError
from datetime import datetime, timedelta
import asyncio

from config import (
    TELEGRAM_BOT_TOKEN, ADMIN_ID, API_URL, HORARIO_ENVIO,
    INTERVALO_RETENTATIVA, TIMEZONE, DATABASE_PATH, LOG_LEVEL
)
from app.database import Database
from app.token_manager import TokenCache
from app.scheduler import init_scheduler, get_scheduler
import config

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

# States for conversations
ADD_UID, CONFIRM_PLAN, SELECT_DAYS = range(3)
REMOVE_UID, RENEW_UID, RENEW_DAYS = range(3, 6)

# Initialize database and scheduler
db = Database(DATABASE_PATH)
token_cache = TokenCache(servers_config=config.SERVERS)


class TelegramBot:
    def __init__(self):
        self.app = None
        self.scheduler = None

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        
        welcome_text = """
🎮 **Bem-vindo ao Free Fire Like Bot!**

Este bot automatiza o envio de likes para sua conta Free Fire.

**Comandos Disponíveis:**
/start - Mostrar esta mensagem
/ajuda - Obter ajuda
/status - Ver status do bot
/info <UID> - Consultar informações do UID
/like <UID> - Enviar like manualmente

**Comandos Administrativos:**
/add <UID> <DIAS> - Adicionar usuário
/remover <UID> - Remover usuário
/listar - Listar todos os usuários
/status_user <UID> - Ver status do usuário
/forcar <UID> - Forçar envio de like
/renovar <UID> <DIAS> - Renovar plano
/historico <UID> - Ver histórico
        """
        
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def ajuda(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ajuda command"""
        help_text = """
📖 **GUIA DE AJUDA**

**COMANDOS DO USUÁRIO:**

/status - Vê o status do seu plano
/info <UID> - Consulta informações de um UID
/like <UID> - Envia um like manualmente

**EXEMPLO:**
/info 123456789
/like 123456789

**COMANDOS ADMINISTRATIVOS:**

/add <UID> <DIAS> - Adiciona um novo usuário
  Exemplo: /add 123456789 30

/remover <UID> - Remove um usuário
  Exemplo: /remover 123456789

/listar - Lista todos os usuários cadastrados

/status_user <UID> - Ver detalhes do usuário
  Exemplo: /status_user 123456789

/forcar <UID> - Força o envio de likes agora
  Exemplo: /forcar 123456789

/renovar <UID> <DIAS> - Renova o plano do usuário
  Exemplo: /renovar 123456789 30

/historico <UID> - Ver histórico de envios
  Exemplo: /historico 123456789

**PLANOS DISPONÍVEIS:**
- 7 dias
- 14 dias
- 30 dias
- 60 dias
- 90 dias
- Ilimitado

**PRECISA DE AJUDA?**
Fale com o administrador!
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        try:
            scheduler = get_scheduler()
            sched_status = scheduler.get_status() if scheduler else None
            
            status_text = f"""
✅ **STATUS DO BOT**

🤖 Bot: {'Online' if sched_status and sched_status['is_running'] else 'Offline'}
👥 Usuários Ativos: {sched_status['active_users'] if sched_status else 0}
⏰ Próximo Envio: {sched_status['next_run_time'] if sched_status else 'Desconhecido'}
🕒 Horário de Envio: {HORARIO_ENVIO}
🔄 Intervalo de Retentativa: {INTERVALO_RETENTATIVA}h
🌍 Fuso Horário: {TIMEZONE}
            """
            
            await update.message.reply_text(status_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await update.message.reply_text("❌ Erro ao obter status", parse_mode='Markdown')

    async def info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /info <UID> command"""
        try:
            if not context.args or len(context.args) != 1:
                await update.message.reply_text("❌ Uso: /info <UID>", parse_mode='Markdown')
                return
            
            uid = context.args[0]
            
            # Validate UID format
            if not uid.isdigit() or len(uid) < 5:
                await update.message.reply_text("❌ UID inválido. Deve conter apenas números.", parse_mode='Markdown')
                return
            
            user = db.get_user(uid)
            
            if not user:
                await update.message.reply_text(f"❌ UID {uid} não encontrado no banco de dados.", parse_mode='Markdown')
                return
            
            plan_status = "Ativo" if user['status'] == 'active' else "Inativo"
            days_left = user['remaining_days'] if user['remaining_days'] else "Ilimitado"
            
            info_text = f"""
👤 **Informações do Usuário**

🆔 UID: `{user['uid']}`
📝 Nick: {user['nickname'] or 'Não informado'}
📊 Status: {plan_status}
📅 Dias Restantes: {days_left}
❤️ Likes Totais: {user['likes_count']}
✅ Sucessos: {user['success_count']}
❌ Falhas: {user['fail_count']}
🕒 Último Envio: {user['last_like_attempt'] or 'Nunca'}
            """
            
            await update.message.reply_text(info_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in info command: {e}")
            await update.message.reply_text("❌ Erro ao obter informações", parse_mode='Markdown')

    async def add_user_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start add user conversation"""
        if update.effective_user.id != int(ADMIN_ID):
            await update.message.reply_text("❌ Apenas administradores podem usar este comando.", parse_mode='Markdown')
            return ConversationHandler.END
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("❌ Uso: /add <UID> <DIAS>", parse_mode='Markdown')
            return ConversationHandler.END
        
        uid = context.args[0]
        days = context.args[1]
        
        if not uid.isdigit() or not days.isdigit():
            await update.message.reply_text("❌ UID e DIAS devem ser números.", parse_mode='Markdown')
            return ConversationHandler.END
        
        # Check if user exists
        user = db.get_user(uid)
        
        if not user:
            db.add_user(uid)
            user = db.get_user(uid)
        
        context.user_data['uid'] = uid
        context.user_data['days'] = int(days)
        
        # Show confirmation
        confirm_text = f"""
👤 **Confirmação**

🆔 UID: `{uid}`
📅 Plano: {days} dias

Deseja ativar o automático?
        """
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirmar", callback_data='confirm_add'),
                InlineKeyboardButton("❌ Cancelar", callback_data='cancel_add')
            ]
        ]
        
        await update.message.reply_text(
            confirm_text, 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
        return CONFIRM_PLAN

    async def confirm_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm adding user"""
        query = update.callback_query
        await query.answer()
        
        uid = context.user_data.get('uid')
        days = context.user_data.get('days')
        
        if not uid or not days:
            await query.edit_message_text("❌ Dados inválidos")
            return ConversationHandler.END
        
        # Activate plan
        if db.activate_plan(uid, days):
            success_text = f"""
✅ **Plano Ativado!**

🆔 UID: `{uid}`
📅 Dias: {days}
⏰ Expiração: {datetime.now() + timedelta(days=days)}

O bot iniciará o envio automático de likes às {HORARIO_ENVIO}
            """
            await query.edit_message_text(success_text, parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Erro ao ativar plano")
        
        return ConversationHandler.END

    async def cancel_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel adding user"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("❌ Operação cancelada")
        return ConversationHandler.END

    async def remove_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remover command"""
        if update.effective_user.id != int(ADMIN_ID):
            await update.message.reply_text("❌ Apenas administradores podem usar este comando.", parse_mode='Markdown')
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("❌ Uso: /remover <UID>", parse_mode='Markdown')
            return
        
        uid = context.args[0]
        
        if db.remove_user(uid):
            await update.message.reply_text(f"✅ Usuário {uid} removido com sucesso!", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Erro ao remover usuário {uid}", parse_mode='Markdown')

    async def list_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /listar command"""
        if update.effective_user.id != int(ADMIN_ID):
            await update.message.reply_text("❌ Apenas administradores podem usar este comando.", parse_mode='Markdown')
            return
        
        users = db.get_all_active_users()
        
        if not users:
            await update.message.reply_text("❌ Nenhum usuário ativo", parse_mode='Markdown')
            return
        
        list_text = "👥 **Usuários Ativos**\n\n"
        
        for user in users[:20]:  # Limit to 20 users
            list_text += f"🆔 `{user['uid']}` - {user['nickname'] or 'Sem nick'}\n"
            list_text += f"   Status: {user['status']} | Dias: {user['remaining_days']}\n"
        
        if len(users) > 20:
            list_text += f"\n... e mais {len(users) - 20} usuários"
        
        await update.message.reply_text(list_text, parse_mode='Markdown')

    async def history(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /historico command"""
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("❌ Uso: /historico <UID>", parse_mode='Markdown')
            return
        
        uid = context.args[0]
        history = db.get_history(uid, days=30)
        
        if not history:
            await update.message.reply_text(f"❌ Nenhum histórico para {uid}", parse_mode='Markdown')
            return
        
        history_text = f"📅 **Histórico de {uid}**\n\n"
        
        for record in history[:10]:
            date = record['date']
            history_text += f"📌 {date}\n"
            history_text += f"   ✅ {record['success_count']} sucessos\n"
            history_text += f"   ❌ {record['fail_count']} falhas\n"
        
        await update.message.reply_text(history_text, parse_mode='Markdown')

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")

    def run(self):
        """Run the bot"""
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("ajuda", self.ajuda))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("info", self.info))
        
        # Admin commands
        add_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("add", self.add_user_start)],
            states={
                CONFIRM_PLAN: [CallbackQueryHandler(self.confirm_add, pattern='^confirm_add$'),
                               CallbackQueryHandler(self.cancel_add, pattern='^cancel_add$')]
            },
            fallbacks=[CommandHandler("cancel", self.cancel_add)]
        )
        
        self.app.add_handler(add_conv_handler)
        self.app.add_handler(CommandHandler("remover", self.remove_user))
        self.app.add_handler(CommandHandler("listar", self.list_users))
        self.app.add_handler(CommandHandler("historico", self.history))
        
        self.app.add_error_handler(self.error_handler)
        
        logger.info("Bot started polling...")
        self.app.run_polling()


if __name__ == "__main__":
    bot = TelegramBot()
    bot.run()
