// PIN Authentication for User Port
class PinAuth {
    constructor() {
        this.pinOverlay = document.getElementById('pinOverlay');
        this.pinInput = document.getElementById('pinInput');
        this.pinSubmit = document.getElementById('pinSubmit');
        this.pinCancel = document.getElementById('pinCancel');
        this.pinError = document.getElementById('pinError');
        this.pinUserInfo = document.getElementById('pinUserInfo');
        this.currentUser = null;
        
        this.init();
    }
    
    init() {
        if (!this.pinOverlay) return;
        
        this.pinSubmit.addEventListener('click', () => this.submitPin());
        this.pinCancel.addEventListener('click', () => this.hideOverlay());
        this.pinInput.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.pinInput.addEventListener('input', (e) => this.handleInput(e));
    }
    
    handleKeydown(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            this.submitPin();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            this.hideOverlay();
        }
    }
    
    handleInput(e) {
        // Only allow digits
        e.target.value = e.target.value.replace(/[^0-9]/g, '');
    }
    
    showPinForUser(userId, userName) {
        this.currentUser = { id: userId, name: userName };
        this.pinUserInfo.textContent = `Please enter PIN for ${userName}`;
        this.pinInput.value = '';
        this.pinError.style.display = 'none';
        this.pinOverlay.style.display = 'flex'; // Show the PIN overlay
        this.pinInput.focus();
        document.body.style.overflow = 'hidden';
    }
    
    async submitPin() {
        const pin = this.pinInput.value.trim();
        
        if (!pin) {
            this.showError('Please enter a PIN');
            return;
        }
        
        if (pin.length !== 4 || !/^\d{4}$/.test(pin)) {
            this.showError('PIN must be exactly 4 digits');
            return;
        }
        
        try {
            const response = await fetch('/verify_pin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: this.currentUser.id,
                    pin: pin
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // PIN verified successfully - redirect to entries
                window.location.href = `/entries?user_id=${this.currentUser.id}`;
            } else {
                this.showError(data.error || 'Invalid PIN');
                this.pinInput.value = '';
                this.pinInput.focus();
            }
        } catch (error) {
            this.showError('Network error. Please try again.');
            console.error('PIN verification error:', error);
        }
    }
    
    showError(message) {
        this.pinError.textContent = message;
        this.pinError.style.display = 'block';
    }
    
    hideOverlay() {
        this.pinOverlay.style.display = 'none';
        document.body.style.overflow = 'auto';
        this.currentUser = null;
    }
}

// User Click Handler for PIN verification
class UserClickHandler {
    constructor() {
        this.pinAuth = new PinAuth();
        this.init();
    }
    
    init() {
        // Use event delegation to handle clicks on all user cards (including dynamically loaded ones)
        document.addEventListener('click', (e) => {
            if (e.target.closest('.user-card')) {
                this.handleUserClick(e);
            }
        });
        
        // Check for require_pin URL parameter
        this.checkForPinRequirement();
    }
    
    clearPinQueryParams() {
        if (!window.history || !window.location.search) return;
        const url = new URL(window.location.href);
        let mutated = false;
        if (url.searchParams.has('require_pin')) {
            url.searchParams.delete('require_pin');
            mutated = true;
        }
        if (url.searchParams.has('user_id')) {
            url.searchParams.delete('user_id');
            mutated = true;
        }
        if (mutated) {
            const query = url.searchParams.toString();
            const newUrl = query ? `${url.pathname}?${query}` : url.pathname;
            window.history.replaceState({}, document.title, newUrl);
        }
    }
    
    checkForPinRequirement() {
        const urlParams = new URLSearchParams(window.location.search);
        const userId = urlParams.get('user_id');
        const requirePin = urlParams.get('require_pin');
        
        console.log({
            userId: userId,
            requirePin: requirePin,
            fullSearch: window.location.search
        }); // Debug log
        
        if (userId && requirePin === 'true') {
            // Find the user name from the user card
            const userCard = document.querySelector(`[href*="user_id=${userId}"]`);
            if (userCard) {
                const userContainer = userCard.closest('.user-card-container');
                const userName = userContainer.dataset.userName;
                if (userName) {
                    // Show PIN overlay for this user
                    this.pinAuth.showPinForUser(parseInt(userId), userName);
                } else {
                }
            } else {
            }
        } else {
        }
        
        // Clean up query params so reloading doesn't prompt the previous user again
        this.clearPinQueryParams();
    }
    
    async handleUserClick(e) {
        e.preventDefault();
        e.stopPropagation();
        
        const userCard = e.target.closest('.user-card');
        const userContainer = userCard.closest('.user-card-container');
        const userId = this.extractUserIdFromHref(userCard.href);
        const userName = userContainer.dataset.userName;
        
        
        // Check if user has PIN by making a simple request
        try {
            const response = await fetch('/check_user_pin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                if (data.has_pin) {
                    // User has PIN, show PIN overlay
                    this.pinAuth.showPinForUser(userId, userName);
                } else {
                    // User has no PIN, proceed directly
                    window.location.href = userCard.href;
                }
            } else {
                // Fallback: proceed directly
                window.location.href = userCard.href;
            }
        } catch (error) {
            // Fallback: proceed directly
            window.location.href = userCard.href;
        }
    }
    
    extractUserIdFromHref(href) {
        const match = href.match(/user_id=(\d+)/);
        return match ? parseInt(match[1]) : null;
    }
}

// Initialize when DOM is loaded
// Guests Button Handler
class GuestsButton {
    constructor() {
        this.guestsBtn = document.getElementById('guestsBtn');
        this.init();
    }
    
    init() {
        if (this.guestsBtn) {
            this.guestsBtn.addEventListener('click', () => this.handleGuestsClick());
        }
    }
    
    async handleGuestsClick() {
        // Navigate to role id 4 user
        try {
            const resp = await fetch('/api/find_user_by_role/4');
            const data = await resp.json();
            if(resp.ok && data.success){
                window.location.href = `/entries?user_id=${data.user_id}`;
            } else {
                alert('Guests user not found');
            }
        } catch(e){
            alert('Network error finding guests user');
        }
    }
}

document.addEventListener('DOMContentLoaded', function() {
    new UserClickHandler();
    new GuestsButton();
});
