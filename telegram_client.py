import logging
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError
import os
import config
from utils import encrypt_data, decrypt_data

logger = logging.getLogger(__name__)

class TelegramClientManager:
    def __init__(self):
        # You need to get these from https://my.telegram.org/apps
        self.api_id = os.getenv('API_ID', 123456)  # Replace with your API ID
        self.api_hash = os.getenv('API_HASH', 'your_api_hash')  # Replace with your API hash
        self.session_folder = 'sessions'
        
        # Create sessions folder if it doesn't exist
        os.makedirs(self.session_folder, exist_ok=True)
    
    async def start_login(self, phone_number: str) -> dict:
        """Start the login process by sending OTP"""
        try:
            # Create client for this phone
            session_file = f"{self.session_folder}/{phone_number.replace('+', '')}"
            client = TelegramClient(session_file, self.api_id, self.api_hash)
            
            await client.connect()
            
            if await client.is_user_authorized():
                return {
                    'success': False,
                    'error': 'Already logged in',
                    'step': 'already_authorized'
                }
            
            # Send OTP
            await client.send_code_request(phone_number)
            
            # Store client in memory for next step
            return {
                'success': True,
                'step': 'otp_sent',
                'phone': phone_number,
                'client': client
            }
            
        except PhoneNumberInvalidError:
            return {
                'success': False,
                'error': 'Invalid phone number',
                'step': 'invalid_phone'
            }
        except Exception as e:
            logger.error(f"Login start error: {e}")
            return {
                'success': False,
                'error': str(e),
                'step': 'error'
            }
    
    async def verify_otp(self, client, phone: str, otp: str, password: str = None) -> dict:
        """Verify OTP and complete login"""
        try:
            await client.sign_in(phone, otp)
            
            # Get session string
            session_string = client.session.save()
            
            return {
                'success': True,
                'session_string': session_string,
                'client': client
            }
            
        except SessionPasswordNeededError:
            # 2FA enabled
            if password:
                try:
                    await client.sign_in(password=password)
                    session_string = client.session.save()
                    return {
                        'success': True,
                        'session_string': session_string,
                        'client': client
                    }
                except Exception as e:
                    return {
                        'success': False,
                        'error': 'Invalid 2FA password',
                        'step': '2fa_required'
                    }
            else:
                return {
                    'success': False,
                    'step': '2fa_required'
                }
        except Exception as e:
            logger.error(f"OTP verification error: {e}")
            return {
                'success': False,
                'error': str(e),
                'step': 'error'
            }
    
    async def get_me(self, session_string: str) -> dict:
        """Get user info from session"""
        try:
            # Create client from session
            client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
            await client.connect()
            
            me = await client.get_me()
            
            return {
                'success': True,
                'user_id': me.id,
                'username': me.username,
                'first_name': me.first_name,
                'last_name': me.last_name,
                'phone': me.phone
            }
            
        except Exception as e:
            logger.error(f"Get me error: {e}")
            return {
                'success': False,
                'error': str(e)
            }

# Global instance
tg_client_manager = TelegramClientManager()
