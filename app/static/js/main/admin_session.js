// Admin Session Timeout Management
class AdminSessionManager {
    constructor() {
        this.timeoutMinutes = 10;
        this.warningMinutes = 2; // Warn 2 minutes before timeout
        this.checkInterval = 30000; // Check every 30 seconds
        this.lastActivity = Date.now();
        this.warningShown = false;
        
        this.init();
    }
    
    init() {
        // Only run on admin pages
        if (window.location.port === '5001' || window.location.hostname.includes('admin')) {
            this.startSessionMonitoring();
            this.setupActivityTracking();
        }
    }
    
    startSessionMonitoring() {
        setInterval(() => {
            this.checkSessionTimeout();
        }, this.checkInterval);
    }
    
    setupActivityTracking() {
        // Track user activity
        const activityEvents = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart', 'click'];
        
        activityEvents.forEach(event => {
            document.addEventListener(event, () => {
                this.lastActivity = Date.now();
                this.warningShown = false; // Reset warning if user is active
            }, true);
        });
    }
    
    checkSessionTimeout() {
        const now = Date.now();
        const timeSinceActivity = (now - this.lastActivity) / 1000 / 60; // minutes
        const timeUntilTimeout = this.timeoutMinutes - timeSinceActivity;
        
        // Show warning 2 minutes before timeout
        if (timeUntilTimeout <= this.warningMinutes && timeUntilTimeout > 0 && !this.warningShown) {
            this.showTimeoutWarning(timeUntilTimeout);
            this.warningShown = true;
        }
        
        // Redirect if timeout exceeded
        if (timeSinceActivity >= this.timeoutMinutes) {
            this.handleSessionTimeout();
        }
    }
    
    showTimeoutWarning(minutesLeft) {
        const warningModal = document.createElement('div');
        warningModal.id = 'session-warning-modal';
        warningModal.innerHTML = `
            <div class="modal fade show" style="display: block; background: rgba(0,0,0,0.5);" tabindex="-1">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content" style="border: 2px solid #ff6b35;">
                        <div class="modal-header" style="background: linear-gradient(135deg, #ff6b35, #f7931e); color: white;">
                            <h5 class="modal-title">
                                <i class="fas fa-clock"></i> Session Timeout Warning
                            </h5>
                        </div>
                        <div class="modal-body text-center">
                            <div class="alert alert-warning">
                                <i class="fas fa-exclamation-triangle fa-2x mb-3"></i>
                                <h6>Your admin session will expire in ${Math.ceil(minutesLeft)} minutes</h6>
                                <p class="mb-0">Please save your work and refresh the page to extend your session.</p>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-primary" onclick="this.closest('.modal').remove(); location.reload();">
                                <i class="fas fa-refresh"></i> Extend Session
                            </button>
                            <button type="button" class="btn btn-secondary" onclick="this.closest('.modal').remove();">
                                <i class="fas fa-times"></i> Dismiss
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(warningModal);
        
        // Auto-remove after 30 seconds if not dismissed
        setTimeout(() => {
            const modal = document.getElementById('session-warning-modal');
            if (modal) {
                modal.remove();
            }
        }, 30000);
    }
    
    handleSessionTimeout() {
        // Clear any existing warnings
        const existingWarning = document.getElementById('session-warning-modal');
        if (existingWarning) {
            existingWarning.remove();
        }
        
        // Show timeout message and redirect
        const timeoutModal = document.createElement('div');
        timeoutModal.innerHTML = `
            <div class="modal fade show" style="display: block; background: rgba(0,0,0,0.8);" tabindex="-1">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content" style="border: 2px solid #dc3545;">
                        <div class="modal-header" style="background: linear-gradient(135deg, #dc3545, #c82333); color: white;">
                            <h5 class="modal-title">
                                <i class="fas fa-lock"></i> Session Expired
                            </h5>
                        </div>
                        <div class="modal-body text-center">
                            <div class="alert alert-danger">
                                <i class="fas fa-clock fa-2x mb-3"></i>
                                <h6>Your admin session has expired</h6>
                                <p class="mb-0">For security reasons, you have been logged out. Please log in again to continue.</p>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-primary" onclick="window.location.href='/admin/login';">
                                <i class="fas fa-sign-in-alt"></i> Login Again
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(timeoutModal);
        
        // Redirect to login after 3 seconds
        setTimeout(() => {
            window.location.href = '/admin/login';
        }, 3000);
    }
}

// Initialize session manager when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    new AdminSessionManager();
});

