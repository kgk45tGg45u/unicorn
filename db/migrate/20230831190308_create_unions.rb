class CreateUnions < ActiveRecord::Migration[7.0]
  def change
    create_table :unions do |t|
      t.string :name

      t.timestamps
    end
  end
end
