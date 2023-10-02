class PagesController < ApplicationController

  def dashboard
    @balance = Fund2.balance
  end
end
